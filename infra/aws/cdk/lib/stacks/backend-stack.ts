import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecs_patterns from 'aws-cdk-lib/aws-ecs-patterns';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as path from 'path';
import { Construct } from 'constructs';

export class BikeshareBackendStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // IoT Core endpoint — account-wide, not provisioned by CDK.
    // Get it by running:
    //   aws iot describe-endpoint --endpoint-type iot:Data-ATS --region us-east-1
    // Then pass as context when deploying:
    //   cdk deploy BikeshareBackendStack --context iotEndpoint=xxx.iot.us-east-1.amazonaws.com
    const iotEndpoint: string = this.node.tryGetContext('iotEndpoint') ?? '';

    // -------------------------------------------------------------------------
    // VPC
    // Public subnets for ALB + ECS (ECS gets a public IP so it can reach AWS
    // APIs directly — no NAT Gateway needed, saving ~$32/month).
    // Isolated subnets for RDS (no internet access, only reachable from ECS).
    // -------------------------------------------------------------------------
    const vpc = new ec2.Vpc(this, 'Vpc', {
      vpcName: 'bikeshare-vpc',
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'isolated',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    // -------------------------------------------------------------------------
    // Security Groups — each resource only accepts traffic from its upstream
    // -------------------------------------------------------------------------
    const albSg = new ec2.SecurityGroup(this, 'AlbSg', {
      vpc,
      securityGroupName: 'bikeshare-alb-sg',
      description: 'ALB — allows HTTP from internet',
    });
    albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP from internet');

    // ECS accepts traffic only from ALB on gunicorn port
    const ecsSg = new ec2.SecurityGroup(this, 'EcsSg', {
      vpc,
      securityGroupName: 'bikeshare-ecs-sg',
      description: 'ECS — allows traffic from ALB only',
    });
    ecsSg.addIngressRule(albSg, ec2.Port.tcp(8000), 'From ALB');

    // RDS accepts PostgreSQL only from ECS
    const rdsSg = new ec2.SecurityGroup(this, 'RdsSg', {
      vpc,
      securityGroupName: 'bikeshare-rds-sg',
      description: 'RDS — allows PostgreSQL from ECS only',
    });
    rdsSg.addIngressRule(ecsSg, ec2.Port.tcp(5432), 'From ECS');

    // -------------------------------------------------------------------------
    // Secrets Manager — application secrets (auto-generated, never in plaintext)
    // -------------------------------------------------------------------------
    const djangoSecretKey = new secretsmanager.Secret(this, 'DjangoSecretKey', {
      secretName: 'bikeshare/django-secret-key',
      description: 'Django SECRET_KEY',
      generateSecretString: {
        passwordLength: 50,
        excludePunctuation: true,
      },
    });

    const internalApiSecret = new secretsmanager.Secret(this, 'InternalApiSecret', {
      secretName: 'bikeshare/internal-api-secret',
      description: 'Shared secret for Lambda → Django internal endpoints',
      generateSecretString: {
        passwordLength: 32,
        excludePunctuation: true,
      },
    });

    // -------------------------------------------------------------------------
    // RDS PostgreSQL — db.t3.micro in isolated subnets.
    // Password auto-generated and stored in Secrets Manager as bikeshare/db-credentials.
    // -------------------------------------------------------------------------
    const db = new rds.DatabaseInstance(this, 'Db', {
      instanceIdentifier: 'bikeshare-db',
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_15,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [rdsSg],
      databaseName: 'bikeshare',
      credentials: rds.Credentials.fromGeneratedSecret('bikeshare', {
        secretName: 'bikeshare/db-credentials',
      }),
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      backupRetention: cdk.Duration.days(0),
    });

    // -------------------------------------------------------------------------
    // ECS Cluster
    // -------------------------------------------------------------------------
    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc,
      clusterName: 'bikeshare',
    });

    // -------------------------------------------------------------------------
    // Fargate service behind ALB.
    // assignPublicIp: true — containers get a public IP for outbound AWS API
    // calls (ECR pull, Secrets Manager, CloudWatch Logs) without a NAT Gateway.
    // -------------------------------------------------------------------------
    const service = new ecs_patterns.ApplicationLoadBalancedFargateService(this, 'Service', {
      cluster,
      serviceName: 'bikeshare-backend',
      desiredCount: 1,
      cpu: 256,
      memoryLimitMiB: 512,
      assignPublicIp: true,
      taskSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [ecsSg],
      publicLoadBalancer: true,
      taskImageOptions: {
        // CDK builds Dockerfile.prod from the backend/ directory and pushes
        // to ECR automatically during cdk deploy.
        image: ecs.ContainerImage.fromAsset(
          path.join(__dirname, '../../../../../backend'),
          { file: 'Dockerfile.prod' },
        ),
        containerPort: 8000,
        environment: {
          DJANGO_SETTINGS_MODULE: 'bikeshare.settings.production',
          POSTGRES_DB: 'bikeshare',
          POSTGRES_USER: 'bikeshare',
          POSTGRES_HOST: db.dbInstanceEndpointAddress,
          POSTGRES_PORT: '5432',
          AWS_REGION: this.region,
          AWS_IOT_ENDPOINT: iotEndpoint,
        },
        secrets: {
          DJANGO_SECRET_KEY: ecs.Secret.fromSecretsManager(djangoSecretKey),
          INTERNAL_API_SECRET: ecs.Secret.fromSecretsManager(internalApiSecret),
          POSTGRES_PASSWORD: ecs.Secret.fromSecretsManager(db.secret!, 'password'),
        },
        logDriver: ecs.LogDrivers.awsLogs({
          streamPrefix: 'bikeshare-backend',
          logRetention: logs.RetentionDays.ONE_WEEK,
        }),
      },
    });

    // ALB health check — pings Django's /health/ every 30 seconds.
    // If 3 consecutive checks fail, ECS kills and restarts the container.
    service.targetGroup.configureHealthCheck({
      path: '/health/',
      healthyHttpCodes: '200',
      interval: cdk.Duration.seconds(30),
      timeout: cdk.Duration.seconds(10),
      healthyThresholdCount: 2,
      unhealthyThresholdCount: 3,
    });

    // -------------------------------------------------------------------------
    // Outputs
    // -------------------------------------------------------------------------
    new cdk.CfnOutput(this, 'AlbDnsName', {
      value: `http://${service.loadBalancer.loadBalancerDnsName}`,
      description: 'ALB URL — pass as --context djangoInternalUrl=<value> when deploying BikeshareLambdaStack',
    });
  }
}

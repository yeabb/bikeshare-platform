import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';
import { Construct } from 'constructs';

// Absolute path to the lambdas directory from this file's location:
// infra/aws/cdk/lib/stacks/ → ../../../lambdas/ → infra/aws/lambdas/
const LAMBDAS_DIR = path.join(__dirname, '../../../lambdas');

export class BikeshareLambdaStack extends cdk.Stack {
  public readonly eventIngestionFn: lambda.Function;
  public readonly timeoutSweepFn: lambda.Function;
  public readonly stationHeartbeatFn: lambda.Function;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // DJANGO_INTERNAL_URL is set to a placeholder until ECS is deployed (#8).
    // After ECS deploy, redeploy this stack with the real ALB URL:
    //   cdk deploy BikeshareLambdaStack \
    //     --context djangoInternalUrl=http://internal-alb.bikeshare.internal/
    const djangoInternalUrl: string =
      this.node.tryGetContext('djangoInternalUrl') ??
      process.env.DJANGO_INTERNAL_URL ??
      'http://PENDING-SET-AFTER-ECS-DEPLOY/';

    const internalApiSecret: string =
      this.node.tryGetContext('internalApiSecret') ??
      process.env.INTERNAL_API_SECRET ??
      '';

    this.eventIngestionFn = new lambda.Function(this, 'EventIngestionFn', {
      functionName: 'bikeshare-event-ingestion',
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(LAMBDAS_DIR, 'event_ingestion')),
      timeout: cdk.Duration.seconds(30),
      description: 'Receives IoT Core station events and forwards them to Django.',
      environment: {
        DJANGO_INTERNAL_URL: `${djangoInternalUrl}internal/station-event/`,
        INTERNAL_API_SECRET: internalApiSecret,
      },
    });

    this.timeoutSweepFn = new lambda.Function(this, 'TimeoutSweepFn', {
      functionName: 'bikeshare-timeout-sweep',
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(LAMBDAS_DIR, 'timeout_sweep')),
      timeout: cdk.Duration.seconds(30),
      description: 'Marks PENDING commands past expires_at as TIMEOUT.',
      environment: {
        DJANGO_INTERNAL_URL: `${djangoInternalUrl}internal/commands/sweep/`,
        INTERNAL_API_SECRET: internalApiSecret,
      },
    });

    this.stationHeartbeatFn = new lambda.Function(this, 'StationHeartbeatFn', {
      functionName: 'bikeshare-station-heartbeat',
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(LAMBDAS_DIR, 'station_heartbeat')),
      timeout: cdk.Duration.seconds(30),
      description: 'Marks stations that have stopped sending telemetry as INACTIVE.',
      environment: {
        DJANGO_INTERNAL_URL: `${djangoInternalUrl}internal/stations/heartbeat/`,
        INTERNAL_API_SECRET: internalApiSecret,
      },
    });
  }
}

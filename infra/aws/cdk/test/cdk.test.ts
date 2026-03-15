import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { BikeshareBackendStack } from '../lib/stacks/backend-stack';
import { BikeshareLambdaStack } from '../lib/stacks/lambda-stack';
import { BikeshareSchedulerStack } from '../lib/stacks/scheduler-stack';

const env = { account: '446740421737', region: 'us-east-1' };

describe('BikeshareBackendStack', () => {
  const app = new cdk.App();
  const stack = new BikeshareBackendStack(app, 'TestBackendStack', { env });
  const template = Template.fromStack(stack);

  test('creates a VPC', () => {
    template.resourceCountIs('AWS::EC2::VPC', 1);
  });

  test('creates an ECS cluster', () => {
    template.hasResourceProperties('AWS::ECS::Cluster', {
      ClusterName: 'bikeshare',
    });
  });

  test('creates an RDS PostgreSQL instance', () => {
    template.hasResourceProperties('AWS::RDS::DBInstance', {
      DBInstanceIdentifier: 'bikeshare-db',
      DBName: 'bikeshare',
      Engine: 'postgres',
    });
  });

  test('creates three Secrets Manager secrets', () => {
    template.resourceCountIs('AWS::SecretsManager::Secret', 3);
  });

  test('creates an ALB', () => {
    template.resourceCountIs('AWS::ElasticLoadBalancingV2::LoadBalancer', 1);
  });
});

describe('BikeshareLambdaStack', () => {
  const app = new cdk.App();
  const stack = new BikeshareLambdaStack(app, 'TestLambdaStack', { env });
  const template = Template.fromStack(stack);

  test('creates three Lambda functions', () => {
    template.resourceCountIs('AWS::Lambda::Function', 3);
  });

  test('Lambda functions use Python 3.13', () => {
    template.allResourcesProperties('AWS::Lambda::Function', {
      Runtime: 'python3.13',
    });
  });
});

describe('BikeshareSchedulerStack', () => {
  const app = new cdk.App();
  const lambdaStack = new BikeshareLambdaStack(app, 'LambdaStack', { env });
  const stack = new BikeshareSchedulerStack(app, 'TestSchedulerStack', {
    env,
    timeoutSweepFn: lambdaStack.timeoutSweepFn,
    stationHeartbeatFn: lambdaStack.stationHeartbeatFn,
  });
  const template = Template.fromStack(stack);

  test('creates two EventBridge Scheduler schedules', () => {
    template.resourceCountIs('AWS::Scheduler::Schedule', 2);
  });

  test('timeout sweep uses 1-minute rate', () => {
    template.hasResourceProperties('AWS::Scheduler::Schedule', {
      Name: 'bikeshare-timeout-sweep',
      ScheduleExpression: 'rate(1 minute)',
    });
  });

  test('station heartbeat uses 1-minute rate', () => {
    template.hasResourceProperties('AWS::Scheduler::Schedule', {
      Name: 'bikeshare-station-heartbeat',
      ScheduleExpression: 'rate(1 minute)',
    });
  });
});

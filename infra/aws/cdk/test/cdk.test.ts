import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { BikeshareLambdaStack } from '../lib/stacks/lambda-stack';
import { BikeshareSchedulerStack } from '../lib/stacks/scheduler-stack';

const env = { account: '446740421737', region: 'us-east-1' };

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

  test('timeout sweep uses 10-second rate', () => {
    template.hasResourceProperties('AWS::Scheduler::Schedule', {
      Name: 'bikeshare-timeout-sweep',
      ScheduleExpression: 'rate(10 seconds)',
    });
  });

  test('station heartbeat uses 1-minute rate', () => {
    template.hasResourceProperties('AWS::Scheduler::Schedule', {
      Name: 'bikeshare-station-heartbeat',
      ScheduleExpression: 'rate(1 minute)',
    });
  });
});

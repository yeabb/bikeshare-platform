import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import { Construct } from 'constructs';

interface BikeshareSchedulerStackProps extends cdk.StackProps {
  timeoutSweepFn: lambda.Function;
  stationHeartbeatFn: lambda.Function;
}

export class BikeshareSchedulerStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: BikeshareSchedulerStackProps) {
    super(scope, id, props);

    const { timeoutSweepFn, stationHeartbeatFn } = props;

    // IAM role that allows EventBridge Scheduler to invoke both Lambda functions
    const schedulerRole = new iam.Role(this, 'SchedulerInvokeRole', {
      roleName: 'bikeshare-eventbridge-scheduler-role',
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
      inlinePolicies: {
        InvokeLambdas: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: ['lambda:InvokeFunction'],
              resources: [
                timeoutSweepFn.functionArn,
                stationHeartbeatFn.functionArn,
              ],
            }),
          ],
        }),
      },
    });

    // Timeout sweep — every 1 minute.
    // Cleans up orphaned PENDING commands past expires_at. Frequency doesn't
    // affect user experience — the client handles UX via expires_at, and the
    // next unlock attempt unblocks the user via the PENDING guard.
    new scheduler.CfnSchedule(this, 'TimeoutSweepSchedule', {
      name: 'bikeshare-timeout-sweep',
      description: 'Marks PENDING commands past expires_at as TIMEOUT every minute',
      scheduleExpression: 'rate(1 minute)',
      flexibleTimeWindow: { mode: 'OFF' },
      target: {
        arn: timeoutSweepFn.functionArn,
        roleArn: schedulerRole.roleArn,
        retryPolicy: { maximumRetryAttempts: 2 },
      },
    });

    // Station heartbeat — every 1 minute.
    // Marks stations that have stopped sending telemetry as INACTIVE.
    new scheduler.CfnSchedule(this, 'StationHeartbeatSchedule', {
      name: 'bikeshare-station-heartbeat',
      description: 'Marks stations silent for >90s as INACTIVE every minute',
      scheduleExpression: 'rate(1 minute)',
      flexibleTimeWindow: { mode: 'OFF' },
      target: {
        arn: stationHeartbeatFn.functionArn,
        roleArn: schedulerRole.roleArn,
        retryPolicy: { maximumRetryAttempts: 2 },
      },
    });
  }
}

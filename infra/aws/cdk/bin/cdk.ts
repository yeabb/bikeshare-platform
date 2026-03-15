#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { BikeshareLambdaStack } from '../lib/stacks/lambda-stack';
import { BikeshareIotStack } from '../lib/stacks/iot-stack';
import { BikeshareSchedulerStack } from '../lib/stacks/scheduler-stack';

const app = new cdk.App();

const env = {
  account: '446740421737',
  region: 'us-east-1',
};

// --- Deploy order ---
//
// 1. cdk deploy BikeshareLambdaStack
//    Creates the three Lambda functions. DJANGO_INTERNAL_URL will be set
//    to a placeholder until the ECS deploy (#8) is complete.
//
// 2. bash scripts/provision-certs.sh
//    Creates IoT certificates for each station and writes certs-config.json.
//    Run this before deploying BikeshareIotStack.
//
// 3. cdk deploy BikeshareIotStack
//    Creates IoT Things, per-station policies, IoT Rules → Lambda triggers.
//
// 4. cdk deploy BikeshareSchedulerStack
//    Creates EventBridge Scheduler schedules for sweep and heartbeat.
//
// After ECS deploy (#8), update DJANGO_INTERNAL_URL:
//   cdk deploy BikeshareLambdaStack \
//     --context djangoInternalUrl=http://your-internal-alb-url/

const lambdaStack = new BikeshareLambdaStack(app, 'BikeshareLambdaStack', { env });

new BikeshareIotStack(app, 'BikeshareIotStack', {
  env,
  eventIngestionFn: lambdaStack.eventIngestionFn,
});

new BikeshareSchedulerStack(app, 'BikeshareSchedulerStack', {
  env,
  timeoutSweepFn: lambdaStack.timeoutSweepFn,
  stationHeartbeatFn: lambdaStack.stationHeartbeatFn,
});

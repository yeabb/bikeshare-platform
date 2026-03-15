#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { BikeshareBackendStack } from '../lib/stacks/backend-stack';
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
//    to a placeholder until BikeshareBackendStack is deployed.
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
// 5. Get your IoT endpoint:
//    aws iot describe-endpoint --endpoint-type iot:Data-ATS --region us-east-1
//
// 6. cdk deploy BikeshareBackendStack \
//      --context iotEndpoint=xxx.iot.us-east-1.amazonaws.com
//    Provisions VPC, RDS, ECS Fargate, ALB. Outputs the ALB DNS name.
//
// 7. cdk deploy BikeshareLambdaStack \
//      --context djangoInternalUrl=http://<alb-dns-name>/
//    Updates Lambda env vars with the real ALB URL — wires everything together.

new BikeshareBackendStack(app, 'BikeshareBackendStack', { env });

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

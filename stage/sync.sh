#!/usr/bin/env bash
# Push the experiments to the stage runner and pull them there.
#   ./stage/sync.sh [region]            push laptop -> runner   (default ap-southeast-7)
#   ./stage/sync.sh [region] --pull     pull the runner's measurements/ -> laptop (the runner is canonical)
set -euo pipefail
REGION="${1:-ap-southeast-7}"
MODE="${2:-push}"
STACK=bedrock-fundamentals-stage
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUCKET=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='Bucket'].OutputValue" --output text)
INSTANCE=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)
if [ "$MODE" = "--pull" ]; then
  CMD=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
        --parameters "commands=[\"aws s3 sync /home/ec2-user/bedrock-fundamentals/measurements s3://$BUCKET/measurements-from-runner/\"]" --query Command.CommandId --output text)
  aws ssm wait command-executed --region "$REGION" --command-id "$CMD" --instance-id "$INSTANCE" || true
  aws s3 sync "s3://$BUCKET/measurements-from-runner/" "$HERE/measurements/" --exact-timestamps
  echo "pulled the runner's measurements into $HERE/measurements/"
  exit 0
fi
aws s3 sync "$HERE" "s3://$BUCKET/bedrock-fundamentals/" --exclude ".venv/*" --exclude "__pycache__/*" --exclude ".git/*" --exclude "stage/*" --exclude "measurements/*" --exclude "blog/*" --delete
CMD=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
      --parameters 'commands=["/usr/local/bin/pull-scripts"]' --query Command.CommandId --output text)
aws ssm wait command-executed --region "$REGION" --command-id "$CMD" --instance-id "$INSTANCE" || true
aws ssm get-command-invocation --region "$REGION" --command-id "$CMD" --instance-id "$INSTANCE" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text | tail -5
echo "connect: aws ssm start-session --region $REGION --target $INSTANCE"

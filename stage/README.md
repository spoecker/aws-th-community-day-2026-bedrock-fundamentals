# Stage runner: run the experiments from inside AWS

For a conference stage (or any laptop on hostile Wi-Fi): the five scripts run on a small EC2
instance inside AWS, and the laptop only holds one Session Manager terminal over HTTPS. No inbound
ports, no SSH keys, no AWS credentials on the presenting machine, and the concurrency storm's
100+ connections never touch the venue network.

```bash
# 1. deploy (about 3 minutes; the instance installs Python 3.11, tmux and boto3 on first boot)
aws cloudformation deploy --region ap-southeast-7 --stack-name bedrock-fundamentals-stage \
  --template-file stage/ec2-runner.yaml --capabilities CAPABILITY_IAM

# 2. push the scripts (repeat whenever they change)
./stage/sync.sh ap-southeast-7

# 3. get a terminal (needs the Session Manager plugin on the laptop)
aws ssm start-session --region ap-southeast-7 --target <InstanceId from the stack outputs>
sudo -iu ec2-user          # lands in ~/bedrock-fundamentals with the venv active
tmux new -s demo           # a dropped connection then does not kill a running experiment
python3 01_tokens.py
AWS_REGION=ap-southeast-1 python3 04_max_tokens_quota.py   # the source Region is a variable, not the instance's location

# 4. between rehearsals: stop, don't delete (about $0.02/h while running, $0 stopped except the volume)
aws ec2 stop-instances --region ap-southeast-7 --instance-ids <InstanceId>

# 5. afterwards
aws s3 rm s3://<Bucket>/ --recursive && aws cloudformation delete-stack --region ap-southeast-7 --stack-name bedrock-fundamentals-stage
```

Put the instance in the Region you want to call *from* for the routing experiment; for everything
else the calling Region is whatever `AWS_REGION` says. Cost for a rehearsal day: well under $1.

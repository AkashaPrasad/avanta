#!/usr/bin/env bash
# Start or stop the AVANTA API instance.
#
# The instance is the only meaningful AWS cost: ~$49/mo running, ~$4/mo stopped
# (you still pay for the 48 GB EBS volume either way). Stop it between demos.
#
# The public IP is not elastic, so a restart changes it and the DNS record has
# to follow. This script does that for you.
set -euo pipefail

PROFILE="${AWS_PROFILE:-claude-dev}"
REGION="${AWS_REGION:-ap-south-1}"
INSTANCE="${AVANTA_INSTANCE:-i-0c6133684332ef0a9}"
CF_ZONE="${CF_ZONE:-b152483853eef3cccdf50becec773925}"
RECORD="avantaapi.spacesdrive.cc"

aws() { command aws --profile "$PROFILE" --region "$REGION" "$@"; }

state() {
  aws ec2 describe-instances --instance-ids "$INSTANCE" \
    --query 'Reservations[0].Instances[0].State.Name' --output text
}

public_ip() {
  aws ec2 describe-instances --instance-ids "$INSTANCE" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
}

update_dns() {
  local ip="$1"
  [ -n "${CF_API_TOKEN:-}" ] || { echo "  CF_API_TOKEN not set; update $RECORD to $ip by hand"; return; }
  local id
  id=$(curl -s "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records?name=$RECORD" \
        -H "Authorization: Bearer $CF_API_TOKEN" \
        | python3 -c "import sys,json;r=json.load(sys.stdin).get('result') or [];print(r[0]['id'] if r else '')")
  [ -n "$id" ] || { echo "  no DNS record for $RECORD"; return; }
  curl -s -X PATCH "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records/$id" \
    -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
    -d "{\"content\":\"$ip\"}" >/dev/null
  echo "  DNS $RECORD -> $ip"
}

case "${1:-status}" in
  start)
    [ "$(state)" = "running" ] && { echo "already running at $(public_ip)"; exit 0; }
    echo "starting $INSTANCE..."
    aws ec2 start-instances --instance-ids "$INSTANCE" >/dev/null
    aws ec2 wait instance-running --instance-ids "$INSTANCE"
    ip=$(public_ip); echo "  running at $ip"
    update_dns "$ip"
    echo "  waiting for the API to answer (compose restarts on boot)..."
    for _ in $(seq 1 40); do
      code=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "http://$ip/api/v1/health" || true)
      [ "$code" = "200" ] && { echo "  API is up"; exit 0; }
      sleep 15
    done
    echo "  API did not answer in 10 minutes; ssh in and check 'docker compose ps'"
    ;;
  stop)
    [ "$(state)" = "stopped" ] && { echo "already stopped"; exit 0; }
    echo "stopping $INSTANCE (billing drops to the EBS volume only)..."
    aws ec2 stop-instances --instance-ids "$INSTANCE" >/dev/null
    aws ec2 wait instance-stopped --instance-ids "$INSTANCE"
    echo "  stopped"
    ;;
  status)
    s=$(state)
    echo "  instance: $s"
    [ "$s" = "running" ] && echo "  ip:       $(public_ip)"
    echo "  cost:     ~\$49/mo running, ~\$4/mo stopped"
    ;;
  *) echo "usage: $0 {start|stop|status}"; exit 1;;
esac

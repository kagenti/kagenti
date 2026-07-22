# RossoCortex local demo with budget

```bash
cd /Users/aslom/sandbox/kagenti-mvp/kagenti-ykt1

# (1) one terminal open macos sandbox and start RossoCortex inside it

ENABLE_DOCKER=1 ~/sandbox/sandbox.sh zsh

# to start local version instead of container
# export ROSSOCORTEX_CONTAINER_LOCAL_DIR=/Users/aslom/sandbox/kagenti-mvp/kagenti-ykt1/kagenti/scripts/rossocortex-container

./kagenti/scripts/rossoctlx.py log -f


# (2) another terminal - configure budget for two agents: test-agent and klaude

cd /Users/aslom/sandbox/kagenti-mvp/kagenti-ykt1

~/sandbox/sandbox.sh zsh

## setup CLI alias with shell completion
alias rx=/Users/aslom/sandbox/kagenti-mvp/kagenti-ykt1/kagenti/scripts/rossoctlx.py
autoload -Uz compinit && compinit
eval "$(./kagenti/scripts/rossoctlx.py completions --eval --alias rx)"

## Use the same config that is used in sandbox
export XDG_CONFIG_HOME=/Users/aslom/sandbox/kagenti-mvp/kagenti-ykt1

## check version and status

rx version

rx status

## configure agent identities with budget, network acces, and credential injection

rx agents

rx agent test-agent --budget=2

rx agent klaude  --budget=100  --network-deny=api.anthropic.com --network-deny='*.datadoghq.com'

## run test agent


eval "$(/Users/aslom/sandbox/kagenti-mvp/kagenti-ykt1/kagenti/scripts/rossoctlx.py agent test-agent)"

env | sort | egrep 'ANT|CLA|OPE|HTTP'

./kagenti/scripts/simple_llm_test_agent.py


## (3) another sandbox


cd ~/sandbox/other-sandbox

cp /Users/aslom/sandbox/kagenti-mvp/kagenti-ykt1/.config/rossocortex/ca/tls.crt .

~/sandbox/sandbox.sh zsh

# copy env variabels from rx agent klaude run in sandbox that has access to config

# rx agent klaude

# fix certificate path that is not accessible

export SSL_CERT_FILE=$PWD/tls.crt

env | sort | egrep 'ANT|CLA|OPE|HTTP'

claude -p "say hi"
```

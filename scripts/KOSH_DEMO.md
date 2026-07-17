
```bash
cd $DIR

# check directory is empty
find .

# make sure ANTHROPIC_AUTH_TOKEN is set
[ -z "$ANTHROPIC_AUTH_TOKEN" ] && echo "Error: ANTHROPIC_AUTH_TOKEN is not set"

uv run https://kagenti-teleport-setup-team1.apps.epoc002.ete14.res.ibm.com/kagenti-teleport-setup.py  --user alice --password alice123 --test

alias kosh="uv run $PWD/kosh.py"
# optional setup CLI completion
./setup-kosh-completions.sh
exec zsh

kosh local-sandbox list

kosh sandbox list

# possible cleanup
kosh sandbox delete $AGENT_NAME

# export CLAUDE_AUTH_TOKEN=...
# export CLAUDE_CODE_DISABLE_MOUSE=1
# export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1
# export ANTHROPIC_BASE_URL="https://ete-litellm.ai-models.vpc-int.res.ibm.com"
# export ANTHROPIC_MODEL=claude-opus-4-6

export AGENT_NAME=${USER}-agent1

kosh local-sandbox create --name $AGENT_NAME --model claude-opus-4-6

# pwd
# ls /Users/${USER}
# claude
# exit

kosh local-sandbox connect --name $AGENT_NAME

# claude -r

kosh sandbox list

kosh teleport

kosh sandbox list

kosh sandbox connect $AGENT_NAME

# id
# env|grep ANTH

# claude -r

# bob --accept-license --auth-method api-key -p "say hi"

# env|grep BOB


claude -p "say hi"

exit

## === running headless agent

kosh sandbox exec -n  $AGENT_NAME -- claude --dangerously-skip-permissions -p 'say hi from kagenti opehsell sandbox'



# === use kwiki skills

kosh sandbox connect $AGENT_NAME

git clone https://github.com/kagenti/agent-examples.git

mkdir -p .claude/skills/
# install skills from https://github.com/kagenti/agent-examples/tree/main/mcp/wiki_memory_tool/skills
cp -rp agent-examples/mcp/wiki_memory_tool/skills/* .claude/skills/
ls .claude/skills/

claude -r

# run prompt:
# run /kwiki cli query skill for Kagenti form wiki running at https://wiki-memory-service-team1.apps.ykt1.hcp.res.ibm.com/

exit

## === running headless agent

kosh sandbox exec -n $AGENT_NAME -- claude --dangerously-skip-permissions -p 'run /kwiki cli query skill for Kagenti form wiki running at https://wiki-memory-service-team1.apps.ykt1.hcp.res.ibm.com/'


## Using Kagenti from CLI. deploy agents and tools


kosh login --kagenti-url https://kagenti-backend-kagenti-system.apps.epoc002.ete14.res.ibm.com --keycloak-url https://keycloak-keycloak.apps.epoc002.ete14.res.ibm.com --user dev-user --password UonNQPfcSmzPmDSP


kosh deploy tool --name weather-tool --namespace team1 --image ghcr.io/kagenti/agent-examples/weather_tool:latest --protocol streamable_http --port 8000 --target-port     8000

kosh deploy agent --name weather-service --namespace team1 --image ghcr.io/kagenti/agent-examples/weather_service:latest --protocol a2a --framework LangGraph --port 8080      --target-port 8000 --authbridge --spire

kosh catalog agents -n team1
kosh catalog tools -n team1

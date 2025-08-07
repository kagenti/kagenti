# Development Documentation

## Agent and Tool Development

Most of the Agents and Tools are set to use local image to speed up the installation
and deployment `imagePullPolicy: IfNotPresent`. When you want to update the image, or
deploy an image from a different branch in Kagenti **New Agent Import** panel,
you have to explicitly remove the image from kind cluster.

Here are the steps:
```console
kubectl get nodes
NAME                           STATUS   ROLES           AGE   VERSION
agent-platform-control-plane   Ready    control-plane   23h   v1.33.1
kagenti$ docker exec -ti agent-platform-control-plane bash
root@agent-platform-control-plane:/# crictl images
root@agent-platform-control-plane:/# crictl images | grep weather
registry.cr-system.svc.cluster.local:5000/acp-weather-service  v0.0.1   3730634390161   139MB
registry.cr-system.svc.cluster.local:5000/weather-tool         v0.0.1   5196efe63ebab   125MB
root@agent-platform-control-plane:/# crictl rmi 3730634390161
Deleted: registry.cr-system.svc.cluster.local:5000/acp-weather-service:v0.0.1
```

Once the image is gone, you can do a standard **New Agent Import**, and that would create a new image that would be deployed on your instance.

## Testing Kagenti UI Locally
Below are step-by-step instructions to set up and launch the Kagenti UI from a source code. This is usefull when you make a change to the UI code and need to test it without redeploying the UI into the Kubernetes cluster.

### 1. Navigate to the Kagenti UI directory
```bash
cd kagenti/ui
```
### 2. Create a Python Virtual Environment
```bash
python3 -m venv myenv
```
### 3. Activate the Virtual Environment
```bash
source myenv/bin/activate
```
### 4. Install Dependencies
```bash
pip install -r requirements.txt
```
### 5. Launch the Kagenti UI
```bash
streamlit run Home.py
```
### 6. Deactivate the environment
```bash
deactivate
```

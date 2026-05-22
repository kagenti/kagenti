# Creating a Custom Keycloak Build

### Prerequsites

Ensure you have JDK 17 or JDK 21, Git, and Maven installed.

```shell
java -version
git --version
mvn --version
```

### Build the executable

Install Keycloak repo. We have made changes to Keycloak and published them here: 

```shell
git clone https://github.com/maia-iyer/keycloak.git -b spiffe_auth_poc
cd keycloak
```

After making changes to the Keycloak source files, build the jar by running the following command.

```shell
./mvnw -pl quarkus/deployment,quarkus/dist -am -DskipTests clean install
```

You can test the jar by running the following command.
This command will start the Keycloak server on [localhost:8080](localhost:8080).

```shell
java -Dkc.home.dir=./quarkus/server/target/ -jar quarkus/server/target/lib/quarkus-run.jar build --features="admin-fine-grained-authz,token-exchange"
java -jar quarkus/server/target/lib/quarkus-run.jar start-dev
```

### Create a Dockerfile

First, create a clean environment to build the Dockerfile.

```shell
mkdir keycloak_image
cd keycloak_image
```

Then, copy the `quarkus/` folder.

```shell
cp -R <Keycloak folder>/quarkus .
```

Then, we can add the Dockerfile.

```shell
cat <<EOF >Dockerfile
# Use an official Java runtime as a base image
FROM openjdk:17-jdk-slim

# Set the working directory
WORKDIR /app

# Copy the executable
COPY quarkus/ quarkus/

# Expose the port your application runs on
EXPOSE 8080

# Command to run Keycloak
ENTRYPOINT ["java", "-jar", "quarkus/server/target/lib/quarkus-run.jar", "start-dev"]
EOF
```

And now, you can build the image.

```shell
podman build -t quay.io/<username>/keycloak .
```

Then, log into a container image registry.

```shell
podman login quay.io
```

And finally you can push the image to the registry.

```shell
podman push quay.io/<username>/keycloak:latest
```

### Kubernetes manifest

Now you can use the Keycloak image in Kubernetes. For example:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: keycloak-for-tornjak
  namespace: keycloak
spec:
  replicas: 1
  selector:
    matchLabels:
      app: keycloak
  serviceName: keycloak-service
  template:
    metadata:
      labels:
        app: keycloak
    spec:
      containers:
        - name:  keycloak
          image: quay.io/<username>/keycloak:latest
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          env:
            - name: KEYCLOAK_ADMIN
              value: admin
            - name: KEYCLOAK_ADMIN_PASSWORD
              value: admin
            - name: KC_FEATURES
              value: token-exchange,admin-fine-grained-authz
```

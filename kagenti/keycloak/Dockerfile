# syntax=docker/dockerfile:1.7

ARG KEYCLOAK_IMAGE=quay.io/keycloak/keycloak:26.5.2

# Stage 1: build the SPI JAR.
FROM maven:3.9-eclipse-temurin-17 AS jar-builder
WORKDIR /build
COPY pom.xml .
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 mvn -B -DskipTests package

# Stage 2: drop the JAR into Keycloak and run `kc.sh build` so the augmented
# server is baked into the final image (no per-pod build at startup).
FROM ${KEYCLOAK_IMAGE} AS keycloak-builder
COPY --from=jar-builder /build/target/github-org-authenticator-*.jar /opt/keycloak/providers/
RUN /opt/keycloak/bin/kc.sh build

# Stage 3: final runtime image — copy the augmented Keycloak from stage 2.
FROM ${KEYCLOAK_IMAGE}
COPY --from=keycloak-builder /opt/keycloak/ /opt/keycloak/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start"]

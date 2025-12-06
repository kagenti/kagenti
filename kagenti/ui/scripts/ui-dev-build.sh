#!/bin/bash

TAG=$(date +%Y%m%d%H%M%S)
docker build . --tag local/kagenti-ui:${TAG} --load
kind load docker-image --name kagenti local/kagenti-ui:${TAG}
kubectl -n kagenti-system set image deployment/kagenti-ui kagenti-ui-container=local/kagenti-ui:${TAG}
kubectl rollout status -n kagenti-system deployment/kagenti-ui
kubectl get -n kagenti-system pod -l app=kagenti-ui

# Bug Report: MCE Operator Removes HyperShift OIDC S3 Configuration on Upgrade/Reconciliation

## Summary

The HyperShift operator deployment loses its OIDC S3 configuration after MCE (MultiCluster Engine) operator upgrades or reconciliation, causing all AWS HyperShift cluster creations to fail with worker nodes never provisioning.

## Component

- **Product**: Red Hat Advanced Cluster Management (MCE)
- **Component**: hypershift-addon / HyperShift Operator
- **Version**: MCE 2.10.3

## Environment

- **Management Cluster OpenShift Version**: 4.20.x
- **MCE Version**: 2.10.3
- **HyperShift Operator Version**: openshift/hypershift: 6a78b42be85d0d1f9f2c7fc3bf8320fd1d1bc2d3
- **Platform**: AWS (us-east-1)
- **Installation Method**: MCE Operator managing HyperShift

## Description

When using MCE to manage the HyperShift operator on AWS, the operator deployment requires OIDC S3 bucket configuration to enable AWS workload identity federation for hosted cluster nodes. While the OIDC secret and configmap persist across MCE upgrades, the operator deployment arguments that reference them are removed during MCE operator reconciliation.

This causes a configuration drift where:
- ✅ `hypershift-operator-oidc-provider-s3-credentials` secret exists (persists)
- ✅ `oidc-storage-provider-s3-config` configmap exists (persists)  
- ❌ Operator deployment args are missing (removed by MCE)

Without the args, the operator cannot use the OIDC configuration, breaking all AWS cluster creation.

## Steps to Reproduce

1. Install MCE 2.10.3 on OpenShift 4.20+ cluster
2. Configure HyperShift OIDC S3 storage per documentation:
   ```bash
   # Create OIDC secret in hypershift namespace
   oc create secret generic hypershift-operator-oidc-provider-s3-credentials \
     -n hypershift \
     --from-literal=bucket=<bucket-name> \
     --from-literal=region=us-east-1 \
     --from-file=credentials=<aws-creds-file>
   
   # Create OIDC configmap in kube-public namespace  
   oc create configmap oidc-storage-provider-s3-config \
     -n kube-public \
     --from-literal=name=<bucket-name> \
     --from-literal=region=us-east-1
   
   # Patch operator deployment
   oc patch deployment operator -n hypershift --type=json -p '[
     {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--oidc-storage-provider-s3-bucket-name=<bucket>"},
     {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--oidc-storage-provider-s3-region=us-east-1"},
     {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--oidc-storage-provider-s3-credentials=/etc/oidc-storage-provider-s3-creds/credentials"}
   ]'
   ```
3. Attempt to create an AWS HyperShift cluster - succeeds
4. Wait for MCE operator upgrade or trigger reconciliation
5. Attempt to create another AWS HyperShift cluster - fails

## Expected Results

The OIDC S3 configuration should persist across MCE operator lifecycle operations. If the secret and configmap exist, MCE should ensure the operator deployment includes the corresponding arguments.

## Actual Results

After MCE operator upgrades or reconciliation, the operator deployment is missing the OIDC args:
```bash
$ oc get deployment operator -n hypershift -o jsonpath='{.spec.template.spec.containers[0].args}' | grep oidc
# (no output)
```

Hosted cluster creation fails with:
```
HostedCluster Conditions:
  ValidOIDCConfiguration: False
    Message: hypershift wasn't configured with a S3 bucket or credentials, 
             this makes it unable to set up OIDC for AWS clusters. Please 
             install hypershift with the --oidc-storage-provider-s3-bucket-name, 
             --oidc-storage-provider-s3-region and --oidc-storage-provider-s3-credentials 
             flags set.
  ValidAWSIdentityProvider: False - WebIdentityErr
  
NodePool Conditions:
  AWSSecurityGroupAvailable: False
  AllMachinesReady: False - No Machines are created
  
# No EC2 worker instances are ever created
```

## Business Impact

- **Severity**: High  
- **Frequency**: Every MCE operator upgrade (recurring)
- **Impact**: Complete blockage of AWS HyperShift cluster creation in CI/CD pipelines
- **Workaround**: Manual re-patching required after each MCE upgrade

## Analysis

MCE manages the HyperShift operator deployment but lacks a mechanism to declare OIDC configuration persistently:

1. **AddOnDeploymentConfig** (`hypershift-addon-deploy-config`) doesn't support OIDC customizedVariables
2. **MultiClusterEngine CR** doesn't have configOverrides for OIDC settings
3. Manual patches to the deployment are overwritten during MCE reconciliation

The volume and volumeMount for the OIDC credentials secret are preserved, but the args that tell the operator to use them are removed.

## Suggested Fix

MCE should auto-detect OIDC configuration and add the args when:
- Secret `hypershift-operator-oidc-provider-s3-credentials` exists in `hypershift` namespace
- ConfigMap `oidc-storage-provider-s3-config` exists in `kube-public` namespace

Alternatively, expose OIDC configuration via `AddOnDeploymentConfig.spec.customizedVariables`:
```yaml
apiVersion: addon.open-cluster-management.io/v1alpha1
kind: AddOnDeploymentConfig
metadata:
  name: hypershift-addon-deploy-config
  namespace: multicluster-engine
spec:
  customizedVariables:
  - name: oidcStorageProviderS3BucketName
    value: "my-bucket"
  - name: oidcStorageProviderS3Region  
    value: "us-east-1"
```

## Workaround

After each MCE upgrade, re-apply the operator deployment patch:

```bash
oc patch deployment operator -n hypershift --type=json -p '[
  {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--oidc-storage-provider-s3-bucket-name=<bucket>"},
  {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--oidc-storage-provider-s3-region=us-east-1"},
  {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--oidc-storage-provider-s3-credentials=/etc/oidc-storage-provider-s3-creds/credentials"}
]'
```

## Evidence

- **Failed cluster creation** (before fix): https://github.com/kagenti/kagenti/actions/runs/27239848099/job/80440735940
- **Successful cluster creation** (after re-applying patch): https://github.com/kagenti/kagenti/actions/runs/27270755378/job/80539337022

## Additional Information

- Issue has occurred multiple times (2+ confirmed instances)
- Both the secret and configmap have proper ownership/permissions and are not garbage collected
- Volume (`oidc-storage-provider-s3-creds`) and volumeMount survive MCE upgrades
- Only the three `--oidc-storage-provider-s3-*` args are removed from the deployment

## Reproducer

We have a preflight script that can detect and fix this issue:
```bash
# Available at: .github/scripts/hypershift/preflight-check.sh
./preflight-check.sh --auto-fix
```

## Contacts

- **Reporter**: Ryan Jenkins, Red Hat Emerging Tech (Kagenti team)
- **Reviewed by**: Ladas, Red Hat Emerging Tech
- **Date Reported**: June 10, 2026

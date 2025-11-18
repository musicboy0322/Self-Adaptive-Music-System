#!/bin/bash
# ==============================================
# buildAndDeployCarTunes.sh
# Build and Deploy CarTunes Backend on IBM Cloud OpenShift
# ==============================================

set -e

GROUP=6
PROJECT_NAME="acmeair-group${GROUP}"
APP_NAME="cartunes-app"
BUILD_CONTEXT="app"   # directory that contains Dockerfile

# --- Step 0: Check OpenShift login and project. Clean OpenShift environment ---
echo "🔍 Checking OpenShift session..."
if ! oc whoami >/dev/null 2>&1; then
  echo "❌ Not logged in to OpenShift."
  echo "➡️ Run: ibmcloud oc cluster config --cluster <your-cluster-name>"
  echo "➡️ Then: oc login -u apikey -p <your-api-key> <cluster-api-endpoint>"
  exit 1
fi

NAMESPACE=$(oc project -q)
if [ "$NAMESPACE" != "$PROJECT_NAME" ]; then
  echo "❌ Please switch to project $PROJECT_NAME"
  echo "➡️ Run: oc project $PROJECT_NAME"
  exit 1
fi
echo "✅ Using project: $PROJECT_NAME"

oc delete all --all -n acmeair-group6

# --- Step 1: Create or reuse BuildConfig ---
echo "⚙️ Setting up OpenShift build pipeline..."
if oc get bc ${APP_NAME} >/dev/null 2>&1; then
  echo "🔄 BuildConfig exists — reusing it."
else
  echo "🆕 Creating new binary build configuration..."
  oc new-build --binary --name=${APP_NAME} -l app=${APP_NAME}
fi

# --- Step 2: Patch BuildConfig to satisfy resource quota ---
echo "🧩 Ensuring BuildConfig has resource limits (avoiding quota errors)..."
oc patch bc/${APP_NAME} -p '{
  "spec": {
    "resources": {
      "limits": {
        "cpu": "1",
        "memory": "1Gi"
      },
      "requests": {
        "cpu": "200m",
        "memory": "512Mi"
      }
    }
  }
}' || echo "⚠️ BuildConfig patch skipped or already applied."

# --- Step 3: Start build ---
echo "🏗️ Starting CarTunes build inside OpenShift..."
if oc start-build ${APP_NAME} --from-dir=${BUILD_CONTEXT} --follow --wait; then
  echo "✅ Build completed successfully."
else
  echo "⚠️ Build failed or timed out. Check with: oc logs -f build/${APP_NAME}-1"
  exit 1
fi

# --- Step 4: Deploy or update the app ---
echo "🚀 Deploying CarTunes app..."
if oc get deployment ${APP_NAME} >/dev/null 2>&1; then
  echo "🔄 Updating existing deployment..."
  oc set image deployment/${APP_NAME} ${APP_NAME}=image-registry.openshift-image-registry.svc:5000/${PROJECT_NAME}/${APP_NAME}:latest --record
  oc rollout restart deployment/${APP_NAME}
else
  echo "🆕 Creating new deployment..."
  oc new-app ${APP_NAME}:latest --name=${APP_NAME}
  oc set image deployment/${APP_NAME} ${APP_NAME}=image-registry.openshift-image-registry.svc:5000/${PROJECT_NAME}/${APP_NAME}:latest --record

  # Apply resource requests/limits for runtime pod
  oc set resources deployment/${APP_NAME} \
    --limits=cpu=500m,memory=512Mi \
    --requests=cpu=250m,memory=256Mi
fi

# --- Step 5: Expose a public route if missing ---
if ! oc get route ${APP_NAME} >/dev/null 2>&1; then
  echo "🌐 Creating public route..."
  oc expose svc/${APP_NAME}
fi

# --- Step 6: Display final route ---
ROUTE_URL=$(oc get route ${APP_NAME} -o jsonpath='{.spec.host}')
echo "✅ Deployment successful!"
echo "🌍 Access CarTunes backend at: http://${ROUTE_URL}"

echo "📋 Check logs with: oc logs -f deployment/${APP_NAME}"
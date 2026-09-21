# kn-py-cedash

Example Python function with a `Flask` REST API running in Knative. It
decodes and logs incoming [CloudEvents](https://github.com/cloudevents/sdk-python)
(same behavior as `kn-py-echo`), and additionally serves a live dashboard at
`GET /` showing the most recently received CloudEvents (PatternFly 6 UI,
purple theme), refreshing automatically as new events arrive.

## Step 1 - Build with `Buildpacks`

[Buildpacks](https://buildpacks.io) are used to create the container image.

```shell
IMAGE=<docker-username>/<repo>/kn-py-cedash:1.0
pack build -B gcr.io/buildpacks/builder:v1 ${IMAGE}
```

## Step 1 (alternative) - Build with Podman

Instead of Buildpacks, you can build the container image directly from the
included `Containerfile` using [Podman](https://podman.io):

```shell
IMAGE=<registry>/<repo>/kn-py-cedash:1.0
podman build -t ${IMAGE} -f Containerfile .
```

## Step 2 - Test

Verify the container image works by executing it locally.

```bash
podman run -e PORT=8080 -it --rm -p 8080:8080 ${IMAGE}
```

Open `http://localhost:8080/` in a browser to see the dashboard — it starts
empty ("Waiting for CloudEvents...") until an event is posted.

In a separate terminal window, use the `testevent.json` file to validate the
function is working.

```shell
curl -i -d@test/testevent.json localhost:8080
```

You should see a `200 OK` response with the pretty-printed decoded
CloudEvent as the JSON body, and the browser dashboard should update with
the new event within ~3 seconds without a manual reload.

## Step 3 - Deploy

> **Note:** The following steps assume a working Knative environment using
the `default` Rabbit `broker`. The Knative `service` and `trigger` will be
installed in the `vmware-functions` Kubernetes namespace, assuming that the
`broker` is also available there.

Push your container image to an accessible registry once you're done
developing and testing your function logic.

```shell
docker push <docker-username>/<repo>/kn-py-cedash:1.0
```

Edit the `function.yaml` file with the name of the container image from
Step 1 if you made any changes. Deploy the function:

```shell
kubectl -n vmware-functions apply -f function.yaml
```

For testing purposes, the `function.yaml` contains the following
annotations, which will ensure the Knative Service Pod will always run
**exactly** one instance for debugging purposes (otherwise Knative may scale
to zero, which resets the in-memory event buffer on the next cold start):

```yaml
annotations:
  autoscaling.knative.dev/maxScale: "1"
  autoscaling.knative.dev/minScale: "1"
```

## Step 4 - Undeploy

```console
# undeploy function
kubectl -n vmware-functions delete -f function.yaml
```

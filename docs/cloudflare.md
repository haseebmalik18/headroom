# Cloudflare hosting

Public dashboard: **https://hotpath-demo.haseebulhaq55.workers.dev**.
Hosting was first deployed on October 24, 2026.

Headroom uses one Cloudflare Worker with Static Assets and a SQLite-backed Durable
Object. The dashboard and saved investigations come from the assets service. The
Durable Object reserves one shared live run, dispatches the fixed GitHub Actions
workflow, stores its current event buffer, and fans updates out through hibernating
WebSockets. GitHub runs Docker and Nemotron, then posts signed progress updates to
the Worker. The local build still supports the Python server's event stream.

Visitors can select only an allowlisted failure fixture (`random`, `checkout`, or
`catalog`). They cannot provide a seed, repository, model, command, callback URL,
or patch. The coordinator generates the hidden reproduction seed. The workflow claims a run
reservation before it initializes the model client or Docker. The public controls
allow three starts per UTC day, one active run at a time, one new run per visitor
every ten minutes, and at most 100 live sockets. Queue reservations expire after
ten minutes and claimed runs after 65 minutes.

## Free-plan limits

Checked against Cloudflare's official documentation on October 24, 2026:

| Resource | Free allowance / limit |
| --- | --- |
| Static asset requests | Free and unlimited; no additional storage charge |
| Worker requests | 100,000 per day per account, resetting at midnight UTC |
| Worker CPU time | 10 ms per HTTP request; time waiting on network I/O is excluded |
| Worker memory | 128 MB per isolate |
| Outgoing subrequests | 50 per invocation |
| Static files | 20,000 per version, at most 25 MiB per file |

There is no general Worker requests-per-second limit. The daily quota is an
account allowance shared by Workers, not 100,000 investigations. Exceeding the
free allowance causes requests to fail; do not upgrade the account to a paid
Workers plan if a hard $0 hosting budget is required. API routes configured with
`run_worker_first` receive a 429 when that free request limit is exhausted; static
assets continue serving through the asset path.

Sources: [Workers limits](https://developers.cloudflare.com/workers/platform/limits/),
[Static Assets billing](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/).

SQLite-backed Durable Objects are also available on Free: 100,000 requests/day,
13,000 GB-seconds/day of active duration, 5 million rows read/day, 100,000 rows
written/day, and 5 GB total storage. [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/)

Headroom's Docker benchmark lab must run on a separate Docker-capable runner.
The API can coordinate it; 10 ms of Worker CPU cannot execute the investigation.
Nebius inference consumes model credits independently of hosting.

The live page reconnects from the Durable Object's authoritative event buffer and
closes its socket while the tab is hidden. These controls are application limits,
not limits automatically supplied by Cloudflare.

## Local validation

From the repository root (no cloud account needed):

```bash
npm --prefix dashboard ci
npm --prefix dashboard run build:cloudflare
npm --prefix dashboard run test:cloudflare
npm --prefix dashboard run check:cloudflare
npm --prefix dashboard run preview:cloudflare
```

Wrangler is pinned to a Node 20 compatible release in the lockfile. The separate
`dist-cloudflare/` build serves at `/`; it does not replace `dist/`, which serves
the existing local dashboard and GitHub Pages at `/headroom/`.

`check:cloudflare` performs a dry run, not a deployment. `preview:cloudflare`
runs Cloudflare's local runtime. Visit the address it prints, then check the
History links and `/api/status`.

## Connect and publish

The configured Worker name is `hotpath-demo`. A deployment publishes the
dashboard and bundled history JSON publicly at a `workers.dev` URL; no custom
domain or paid service is required. The account itself must be on Workers Free.
If a Worker named `hotpath-demo` already exists, inspect it before deploying or
choose a new name to avoid replacing an unrelated deployment.

After approving account access and deployment:

```bash
# From the repository root, keep login state in the ignored workspace directory.
export XDG_CONFIG_HOME="$PWD/.headroom/cloudflare-config"
cd dashboard
npx wrangler login
npx wrangler whoami
npm run deploy:cloudflare
```

Wrangler login opens Cloudflare's browser authorization flow. Do not put account
tokens or Nebius keys in Vite variables, source files, or chat. Before enabling
live starts, configure:

- GitHub repository secret `NEBIUS_API_KEY` for Token Factory.
- The same random `DEMO_CALLBACK_SECRET` as a GitHub repository secret and a
  Cloudflare Worker secret.
- Cloudflare Worker secret `GITHUB_DISPATCH_TOKEN`, using a short-lived,
  repository-scoped fine-grained token with Actions write access.
- GitHub repository variable `DEMO_URL` set to the public Worker origin.

Keep `LIVE_ENABLED` false until the workflow is present on the default branch and
all four values are configured. Then set it to true and deploy. The status route
reports live execution as enabled only when both Worker secrets are present.

The account ID in `wrangler.jsonc` selects the deployment account; it is not a
secret. Wrangler's OAuth login may be unable to read account subscriptions
(HTTP 403). In that case, confirm Workers Free in the Cloudflare dashboard before
publication; successful login does not establish the billing plan.

After publication, confirm the returned URL serves the dashboard, History loads,
and `/api/status` reports `live.enabled: true`. Start one incident, verify its
GitHub execution link, live evidence, final outcome, and retained artifact. In
Cloudflare's dashboard, monitor request, error, Durable Object, and CPU metrics.

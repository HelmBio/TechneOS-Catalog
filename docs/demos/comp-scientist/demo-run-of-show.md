# TechneOS — Demo Run-of-Show

**Audience:** computational chemists who will implement tools themselves —
evaluating TechneOS for adoption, not a general product overview
**Goal:** sell two things, not one — that workflow automation is worth adopting
at all, *and* that authoring for this platform is easy enough to actually do.
Don't assume the first; this room hasn't already bought into pipelines the way
a platform team would have.
**Format:** live, presenter-driven
**Total time:** 30 minutes, **including Q&A**

---

## The one-sentence spine

> *"Right now, three of your scripts are one person's laptop and a Slack
> thread away from being a repeatable workflow. Watch three tools become one
> versioned pipeline — then watch me add a fourth, live, in one command."*

Two claims, two acts. Act 1 sells the pipeline; Act 2 sells that building for
it is easy. Neither is assumed — both get demonstrated, not asserted.

---

## Before you start: four decisions baked into this script

**1. Do not assume this room already values workflow automation.** They're
computational chemists who write their own tools — which usually means
scripts run by hand, chained by memory, re-run when someone remembers to.
That's not a knock; it's the default, and it's exactly the habit you're
selling them out of. Act 1 has to earn "pipelines are worth it," not gesture
at it in ninety seconds like a room that already agreed would tolerate.

**2. Act 2 is still the centerpiece, but it no longer gets to eat Act 1's
time.** The pitch has two legs now: automation is worth adopting, and
adopting it doesn't cost you your workflow. Cutting Act 1 to nothing to
protect Act 2 would win the second argument and lose the first — and the
second argument doesn't matter to someone who hasn't bought the first.

**3. `molecule-property-calculator` must not already be registered when you go
live.** Unchanged from before, still the highest operational risk on this
list: if registration errors "already exists," the entire live-authoring beat
falls flat in front of the one audience that will notice. Exact commands in
pre-flight.

**4. Do not demo the Assistant using the freshly-registered tool.** Also
unchanged: the `techneos.platform_assistant_tools` entry point is real and
verified — `molecule-property-calculator` is literally the reference example
named in the platform's own source comments — but discovery only runs at
agent-service startup, not per request. Registering live won't make the
Assistant able to use it without a restart you haven't scripted. Describe the
capability; don't stage a demo that quietly depends on a restart you didn't
do.

---

## Pre-flight

### T-24 hours

- [ ] **Confirm `molecule-property-calculator` is NOT registered on
      `techneos.example.com`.** Check the portal's Tools page, or:
      ```bash
      bin/unregister.sh tool molecule-property-calculator --env=prod
      ```
      Run this even if you *think* it's clean — a leftover registration from a
      prior rehearsal is invisible until you click Register live and it errors.
- [ ] **Rehearse the full Act 2 sequence once, for real**, against `--env=prod`:
      author (or confirm) the tool, run
      `bin/register.sh tools/molecule-property-calculator --env=prod --activate`,
      confirm it appears in the portal, run it against `compounds.json`,
      confirm results render. This also warms the local `uv`/pip cache for
      `rdkit`, so the live install doesn't stall on a cold download.
- [ ] **Immediately after rehearsal, unregister it again:**
      ```bash
      bin/unregister.sh tool molecule-property-calculator --env=prod --yes
      ```
      Then re-check the portal. Easy to rehearse, easy to forget to undo —
      worth its own checklist line.
- [ ] Register the hit-triage pipeline if not already, and have one completed
      run bookmarked (`/pipeline-runs/<id>`). Act 1 walks through this run in
      real narrative detail this time — rehearse the walkthrough itself, not
      just the click path.
- [ ] Create/confirm the scientist-role demo account.

### T-30 minutes

- [ ] **Re-verify `molecule-property-calculator` is still absent** — someone
      else on the team, a CI job, or your own rehearsal muscle memory can
      silently undo the step above. Check the portal Tools page one more time,
      immediately before you start.
- [ ] Portal reachable, logged in as the scientist account.
- [ ] Terminal open at the `techneos-catalog` repo root, `--env=prod` config
      confirmed (`cat .env.prod` if in doubt — `PLATFORM_PORTAL_URL` should
      read `https://techneos.example.com`).
- [ ] `compounds.json` (from `pipelines/hit-triage/examples/`) on the desktop —
      you use the same file in both acts.
- [ ] Browser zoom 125–150%, notifications off.

### T-5 minutes — tab order

| Tab | Contents |
|---|---|
| 1 | The completed hit-triage run (`/pipeline-runs/<id>`) — **start here** |
| 2 | Terminal, at `techneos-catalog` repo root |
| 3 | `tools/molecule-property-calculator/tool_def.json` in an editor |
| 4 | `tools/molecule-property-calculator/src/molecule_property_calculator/calculator.py` |
| 5 | `tools/molecule-property-calculator/pyproject.toml` |
| 6 | Portal Tools page (`/tools`) — confirm empty of this tool right before you start |
| 7 | Architecture diagram |

---

## Act 0 — Cold open (90 seconds, no screen)

This room hasn't heard of TechneOS before today — give it one sentence of
orientation before the pain-point story, so nobody's still silently asking
"wait, what is this" three minutes in. One sentence, not a slide:

> "Quick context before I dive in — TechneOS is an AI-native data and compute
> platform for drug discovery. You can also think of it as the operating
> system for research. Take the hit triage workflow as an example — the
> reference pipeline in the TechneOS platform can be used as a template for
> your own workflows and pipelines.
>
> Say your team has just finished a HTS campaign, and you need to triage
> these 'hits' to a smaller set for experimental validation. You might have a
> script to filter out the PAINS (pan-assay interfering compounds) and
> reactive compounds; your colleague might have a clustering algorithm to
> pick a representative from a chemical family, and you might even have a
> docking model to predict the binding affinity to a target. All these are
> doable and important in advancing your research objectives, but what's
> lacking is scalability, traceability and reproducibility. I am going to
> show you those exact steps as one shared and versioned pipeline. Then I am
> going to show you it's just one command line to register your custom tool
> into the platform, which can be incorporated into any appropriate
> pipeline."

Then share.

---

## Act 1 — Make the case for the pipeline (7 minutes)

**Screen:** the completed hit-triage run, tab 1. You are not running this
live — the point here is the narrative, not the click path, and docking is
the one genuinely slow, failure-prone step in this repo. Walk the *outputs*
of a real run in real detail; this act does actual persuasive work, so don't
rush it into a glance.

> "Three tools, chained: a structure-alerts filter, a clustering step, and
> AutoDock Vina. Seventeen compounds went in — mostly clean, drug-like,
> metformin among them — but I left four in that shouldn't survive: two
> PAINS, two reactive warheads. And one string that isn't valid chemistry
> at all."

**Open `screen_alerts` outputs.**

> "Four flagged and dropped, as expected. And the invalid SMILES didn't take
> the whole run down with it — it's recorded as a failed record, not a crash.
> That's the difference between a script you babysit and a step that
> tolerates a dirty library. Real screening libraries are dirty; this is the
> part that usually breaks the script someone wrote for a clean example."

**Open `cluster_compounds` outputs.**

> "Survivors grouped into chemical families, one representative each. This is
> the step that actually saves money — you dock representatives, not the
> whole library. It's also usually the step that lives on one laptop, because
> it's fiddly enough that nobody wants to rewrite it as a shared service."

**Open the finished `dock_vina` step — ranked hits.**

> "Ranked by predicted affinity, poses downloadable. Three tools, three
> different failure modes, three different reasons each one used to live
> somewhere fragile — now one pipeline, one submit, one record of exactly
> what happened."

**Open Versions — land this, don't rush it:**

> "And it's pinned. Which tool version ran at each step, which parameters.
> Eighteen months from now, when someone asks why a compound got dropped, you
> open this version instead of asking whoever still remembers writing the
> filter script. That's the actual value of turning three scripts into a
> pipeline — not convenience, memory."

Close the act with the turn toward Act 2:

> "So that's the case for automating the workflow. The question you're
> actually here with is what it costs to get your own tools into it. Let's
> find out — live."

---

## Act 2 — Author, register, and run a tool, live (13 minutes)

### 2.1 The contract (3 min)

**Screen:** tab 3, `tool_def.json`.

> "This is the whole contract between your code and the platform. Input
> schema, output schema, parameters. `molecule-property-calculator` takes a
> list of SMILES — plain strings or `{smiles, id}` objects — and gives back
> molecular weight, LogP, TPSA, rotatable bonds, ring counts, the usual
> descriptor set."

**Screen:** tab 4, `calculator.py`.

> "And here's the code behind it. This is not platform code — it's RDKit
> calls anyone in this room could have written this afternoon. A hundred and
> eighty-nine lines, no framework, no boilerplate for the platform itself."

Scroll to `run(inputs, params)` specifically:

> "The only thing the platform requires is this shape: a function that takes
> inputs and params, returns a dict. That's the entire integration surface."

**Screen:** tab 5, `pyproject.toml`, point at `[tool.techneos]`:

> "Delivery mode, entry point, done. `pypi` because this is pure Python —
> there's a `container` mode too, for anything with a binary dependency you
> wouldn't want to make everyone install."

If there's any signal of interest, point at the
`[project.entry-points."techneos.platform_assistant_tools"]` block; otherwise
save it for Q&A:

> "This line also means the platform's built-in AI Assistant can call this
> function directly, not just look it up. I won't demo that today — it needs
> a service restart to take effect after a fresh registration, and I'd rather
> tell you that than fake it. It's real, though — it's actually the reference
> example named in the platform's own source code."

### 2.2 The command (3 min)

**Screen:** tab 2, terminal.

```bash
bin/register.sh tools/molecule-property-calculator --env=prod --activate
```

Run it. Narrate while it runs — this takes real seconds, not zero:

> "Builds the wheel, publishes it to the platform's own package index — not
> public PyPI — and registers the tool through the gateway API. Publishing to
> the platform's index is what guarantees a client always matches the
> deployment it's talking to."

When it completes, **switch to the portal, refresh Tools (tab 6).**

> "There it is. I didn't write a line of frontend code — that run form was
> generated from the schema you just saw. Nobody adding a tool writes UI."

### 2.3 Run it (5 min)

Click into the newly-registered tool, **Run**.

> "Same compounds from the hit-triage run in Act 1 — `compounds.json`. Let's
> get real descriptors on all seventeen."

Upload, submit. Near-instant — no docking, no cold container start, genuinely
safe to run live start to finish.

> "MW, LogP, TPSA, rotatable bonds, ring counts, per compound. And the ones
> that failed structure-alerts in Act 1 are still right here — this tool
> doesn't know or care about that filter. That's the other half of the
> pitch: small, composable tools instead of one script that has to know
> everything, chained together the way you just watched in Act 1."

If time remains, toggle `detailed: true` and rerun to show a parameter
actually changing the output shape — cut this first if you're short.

### 2.4 Where it runs, one sentence

> "This ran as a `pypi` tool, straight into a worker. Container tools run the
> same way but in Docker, AWS Batch, Slurm, or routed to a person for
> non-computational work — same registration path, different backend."

The architecture diagram has its own moment in the close — don't pull it up
here even if you're tempted to; showing it twice blunts the payoff.

---

## Act 3 — Close (2 minutes)

Two beats, in this order: show the mechanism, then answer the question the
cold open opened with. Don't reverse the order — the diagram lands better as
"here's how" once the room has already seen the thing work twice.

### 3.1 How it works (tab 7 — architecture diagram)

> "Quick look under the hood before we wrap. Everything you watched — the
> pipeline run and the tool registration — goes through one gateway. Behind
> it, eight services, each fulfilling one of the platform's capabilities —
> from datasets and tools to pipelines and agents.
> Execution runs on Airflow, and the backend is swappable — Docker, AWS
> Batch, or Slurm, depending on the step. Your tool doesn't have to
> know any of this, because the platform absorbs the complexity of running it
> anywhere."

Keep this to what's on the diagram — this is "how," not a second Q&A.

### 3.2 The counter to the cold open

Go back to the exact words you opened with and answer them one by one — this
is the close that makes the whole session feel like one argument, not two
demos back to back:

> "In my opening, I named three things many research organizations struggle
> with when it comes to computational pipelines: scalability, traceability,
> and reproducibility. If that's true for your team too, I hope what you
> just witnessed made the case for TechneOS. Scalability: the same pipeline
> definition runs on your laptop or a cluster, by you or other colleagues.
> Traceability: every run pinned to the exact tool versions and parameters
> that produced it. Reproducibility: register once, and it stops being
> tribal knowledge on one person's machine — it's a shared, versioned
> artifact anyone on your team can run, extend, or audit. And better yet,
> none of this changes how you do science — it expedites it. The tools you
> write, the judgment calls, the methodology: still entirely yours. What's
> different is how fast you get from that work to a result. So — ready to
> give it a try?"

**The ask** — concrete, not "any questions":

> "Bring me a tool you actually use. Let's register it against your data
> before you leave today."

---

## Failure fallbacks

| If this breaks | Say this | Then do this |
|---|---|---|
| Registration errors "already exists" | *"Looks like this didn't get cleaned up from testing — let's upsert it."* | `bin/register.sh tools/molecule-property-calculator --env=prod --activate --upsert` |
| Registration hangs on dependency install | *"RDKit's a real download the first time — let's not watch a progress bar."* | Narrate through it (you pre-warmed the cache in rehearsal, so this should be seconds — if it's not, the cache warm-up didn't take, not the platform) |
| Portal doesn't show the new tool after refresh | *"While that catches up — same thing from the CLI."* | `techneos tool list` — reinforces the portal is one client of the API, not the source of truth |
| Tool run fails / bad SMILES | *"Good — this is what a real failure looks like."* | Point at the `errors` array; the invalid SMILES from `compounds.json` is expected to land there, not crash the run |
| Someone asks to see the Assistant use it live | *"Fair question — honest answer is it needs a restart to pick up a fresh registration. I'd rather tell you that than fake it."* | Move on; this audience will respect the straight answer more than a smooth non-answer |
| Portal/stack fully down | Don't debug on screen. | `tool_def.json` + `calculator.py` walkthrough + architecture diagram + narrate Act 1 from memory. Same story, no live software. |

**Rule:** never debug on screen for more than ten seconds — a 30-minute slot
doesn't have the runway a longer one would.

---

## Q&A preparation (budget ~6–7 minutes within the 30)

Two threads of questions now — don't over-prepare for only the tool-authoring
ones.

**On whether automation is worth it at all:**

- *"I can just run my scripts myself — why does this matter?"* — Until someone
  else needs the result, or you need to explain a decision eighteen months
  later. The pipeline's Versions section is the answer, not an argument.
- *"What if my workflow doesn't look like a clean DAG?"* — Most don't, at
  first. The DAG is the pipeline's fixed shape; a version pins tool
  versions and parameters without redrawing it — you're not required to get
  the shape right before you start.
- *"Doesn't this just move the maintenance burden?"* — Yes, deliberately —
  from "whoever remembers how the laptop script works" to a versioned
  artifact anyone on the team can open.

**On whether authoring for it is easy:**

- *"What if my tool isn't pure Python?"* — `container` delivery mode; same
  registration path, Docker image instead of a wheel.
- *"How do dependencies get resolved?"* — `pyproject.toml` dependencies,
  installed at registration/dispatch time from the platform's own index.
- *"What happens when I need to change the tool later?"* — New tool version,
  pinned per pipeline version; old runs keep their original pins.
- *"Do I have to write tests to register something?"* — Not required, but
  `build_and_register.py` validates the entry point is importable before
  it'll publish — a broken function fails fast, not on first use.
- *"Can the Assistant actually call my tool?"* — Yes, via the
  `techneos.platform_assistant_tools` entry point, verified in the platform's
  own code — but only after an agent-service restart picks up the new
  registration. Say this plainly if asked.
- *"Does our data leave our infrastructure?"* — Self-hosted is first-class:
  Docker Compose today, AWS CodePipeline for production.
- *"Who can run what?"* — RBAC scoped `own` / `team` / `org` / `platform` per
  resource type.
- *"What's the actual integration surface?"* — One function,
  `run(inputs, params) -> dict`. That's genuinely it.

**Know these numbers:** ~75k lines, 8 domain microservices, one command from
script to registered tool, near-zero runtime for a descriptor calculation.

---

## Timing

| Segment | Target | Hard cap |
|---|---|---|
| 0 — Cold open | 1:30 | 2:00 |
| 1 — Make the case for the pipeline | 7:00 | 8:00 |
| 2 — Author, register, run (live) | 13:00 | 15:00 |
| 3 — Close (diagram + callback) | 2:00 | 2:30 |
| **Presentation subtotal** | **23:30** | **27:30** |
| Q&A | 6:30 | remaining time |
| **Total** | **30:00** | **30:00** |

If you're running long, cut in this order: 2.3's `detailed=true` toggle first,
then 3.1's diagram walkthrough down to one sentence ("everything you watched
runs through one gateway, on Airflow, with swappable compute backends" —
skip the service-by-service detail), then Act 1's `cluster_compounds` beat
(keep `screen_alerts` and Versions in Act 1 — those two carry the whole
automation argument). Never cut 2.1, 2.2, or 3.2's callback — the contract,
the live command, and the answer to the cold open are what make this one
argument instead of two demos back to back. Never cut Act 1 to nothing either
— this room hasn't already bought the pipeline argument, and neither Act 2 nor
the callback in 3.2 land without it.

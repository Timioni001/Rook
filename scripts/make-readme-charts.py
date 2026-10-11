#!/usr/bin/env python3
"""Draw the two README charts from numbers this repository measures, not from numbers typed in.

    python3 scripts/make-readme-charts.py        # writes docs/images/*.svg

Both charts run the engine first: one clean incident per playbook, then all scenarios end to end.
If a playbook changes, the chart changes with it, which is the only way a chart in a README stays
true. Colours are the dashboard's own two accent tokens, checked for colour-blind separation, and
every bar carries its number so the chart never depends on colour alone.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rook.domain import Principal                                          # noqa: E402
from rook.engine import Engine                                             # noqa: E402
from rook.playbooks import PLAYBOOKS                                       # noqa: E402
from rook.sandbox import SCENARIOS, Sandbox, playbook_of                   # noqa: E402
from rook.store import Store                                               # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images"
APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])
# The dashboard's own tokens. --ok and --info pass the adjacent-pair colour-blind checks on the
# paper surface; ink is for text only, never for a series.
INK, MUTED, PAPER, LINE = "#101010", "#5c5a54", "#fbfaf7", "#d9d6cd"
STEPS, CHECKS = "#1f4fbf", "#1d7a2e"
FONT = "'Space Grotesk', 'DejaVu Sans', system-ui, sans-serif"
MONO = "'Space Mono', ui-monospace, monospace"
# One scenario per playbook where nothing is injected: the shape of the work, without faults.
CLEAN = {"cover": "cover_clean", "care": "referral_clean", "offboarding": "clean",
         "leak": "leak_clean", "outage": "outage_clean", "fixtures": "fixtures_clean"}


def run(scenario):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario)
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario=scenario)
    e.run(inc.id)
    for _ in range(40):
        pending = [a for a in st.actions(inc.id) if a.status.value == "needs_approval"]
        if not pending:
            break
        for a in pending:
            e.approve(inc.id, a.id, APPROVER)
        e.run(inc.id)
    return e.finalize(inc.id)


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=13, fill=INK, anchor="start", weight=400, font=FONT):
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')


def frame(w, h, title, subtitle, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(title)}">'
            f'<rect width="{w}" height="{h}" rx="16" fill="{PAPER}" stroke="{LINE}" stroke-width="2"/>'
            + text(28, 40, title, 19, INK, weight=700)
            + text(28, 62, subtitle, 13, MUTED)
            + body + "</svg>\n")


def legend(x, y, items):
    out, dx = [], 0
    for label, colour in items:
        out.append(f'<rect x="{x + dx}" y="{y - 9}" width="11" height="11" rx="3" fill="{colour}"/>')
        out.append(text(x + dx + 17, y, label, 12, MUTED))
        dx += 22 + int(6.6 * len(label))
    return "".join(out)


def work_per_playbook():
    """Grouped bars: what one incident of each kind actually involves."""
    rows = []
    for key, scenario in CLEAN.items():
        rep = run(scenario)
        rows.append((PLAYBOOKS[key].name, len(rep["actions"]), len(rep["conditions"]),
                     rep["metrics"]["systems_touched"]))
    rows.sort(key=lambda r: -(r[1] + r[2]))
    top, left, right, rowh, barh, gap = 108, 212, 56, 46, 13, 5
    w, h = 880, top + rowh * len(rows) + 28
    scale = (w - left - right) / max(r[1] + r[2] for r in rows) * 0.62
    body = [legend(28, 86, [("Steps Rook ran", STEPS), ("Independent checks", CHECKS)])]
    for i, (name, steps, checks, systems) in enumerate(rows):
        y = top + i * rowh
        body.append(text(28, y + 12, name, 13, INK, weight=600))
        body.append(text(28, y + 29, f"{systems} system{'' if systems == 1 else 's'}", 11, MUTED, font=MONO))
        for j, (value, colour) in enumerate(((steps, STEPS), (checks, CHECKS))):
            by = y + j * (barh + gap)
            width = max(2.0, value * scale)
            body.append(f'<rect x="{left}" y="{by}" width="{width:.1f}" height="{barh}" rx="4" fill="{colour}"/>')
            body.append(text(left + width + 8, by + barh - 2, value, 12, MUTED, font=MONO))
    body.append(f'<line x1="{left}" y1="{top - 10}" x2="{left}" y2="{h - 22}" stroke="{LINE}" stroke-width="2"/>')
    return frame(w, h, "One incident, by kind",
                 "Steps the agent carried out, and checks it then made against the live systems. "
                 "Measured from a clean run of each playbook.", "".join(body))


def outcomes():
    """Stacked bars: how every scenario ends, by industry. Stopping is an outcome, not a failure."""
    groups = {"cover": "Healthcare", "care": "Healthcare", "offboarding": "IT & security",
              "leak": "IT & security", "outage": "Engineering", "fixtures": "Sport & clubs"}
    tally = {}
    for scenario in sorted(SCENARIOS):
        rep = run(scenario)
        g = tally.setdefault(groups[playbook_of(scenario)], [0, 0])
        g[0 if rep["status"] == "closed_verified" else 1] += 1
    order = ["Healthcare", "IT & security", "Engineering", "Sport & clubs"]
    rows = [(g, *tally[g]) for g in order if g in tally]
    total_closed, total_stopped = (sum(r[1] for r in rows), sum(r[2] for r in rows))
    top, left, right, rowh, barh = 112, 212, 56, 44, 26
    w, h = 880, top + rowh * (len(rows) + 1) + 34
    # One scale for every row, the all-scenarios row included, so the bars stay comparable.
    scale = (w - left - right - 46) / (total_closed + total_stopped)
    body = [legend(28, 90, [("Closed, every check passed", CHECKS), ("Stopped, with a reason", STEPS)])]
    for i, (name, closed, stopped) in enumerate(rows + [("All scenarios", total_closed, total_stopped)]):
        y = top + i * rowh
        last = i == len(rows)
        body.append(text(28, y + 18, name, 13, INK, weight=700 if last else 600))
        x = left
        for value, colour in ((closed, CHECKS), (stopped, STEPS)):
            width = value * scale
            if width > 0:
                body.append(f'<rect x="{x}" y="{y}" width="{max(width - 2, 1):.1f}" height="{barh}" '
                            f'rx="4" fill="{colour}"/>')
                if width > 26:
                    body.append(text(x + width / 2 - 1, y + 18, value, 12, PAPER, anchor="middle",
                                     weight=700, font=MONO))
            x += width
        body.append(text(x + 8, y + 18, f"{closed + stopped}", 12, MUTED, font=MONO))
        if last:
            body.append(f'<line x1="28" y1="{y - 10}" x2="{w - 28}" y2="{y - 10}" stroke="{LINE}" stroke-width="2"/>')
    return frame(w, h, "Every scenario, and how it ends",
                 f"{total_closed + total_stopped} scenarios run end to end. {total_stopped} of them stop "
                 "on purpose: no slot, nobody to tell, a key that would break a service.", "".join(body))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, svg in (("work-per-playbook.svg", work_per_playbook()), ("scenario-outcomes.svg", outcomes())):
        (OUT / name).write_text(svg)
        print("wrote", OUT / name)

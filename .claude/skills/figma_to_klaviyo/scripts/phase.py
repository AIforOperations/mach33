#!/usr/bin/env python3
"""Per-phase wall-clock timing for a build run (so cold-run speed is measured, not guessed).

Usage:
  python3 phase.py <builddir> "<label>"     # stamp a milestone; prints delta + running total
  python3 phase.py <builddir> --report      # print the full phase table for the run

The agent stamps a milestone at each front-half boundary the deterministic build.py can't see:
  start -> reads-done -> export-done -> plan-done -> (build.py runs) -> verify-done
The first stamp is t=0. Each later stamp prints the delta from the previous stamp and the total
since start. --report renders the whole table (drop it into speed_goal_tracking.md)."""
import sys, os, time

def main():
    if len(sys.argv) < 3:
        sys.exit("usage: phase.py <builddir> <label|--report>")
    builddir, label = sys.argv[1], sys.argv[2]
    os.makedirs(builddir, exist_ok=True)
    f = os.path.join(builddir, "phases.tsv")
    rows = []
    if os.path.exists(f):
        rows = [l.split("\t") for l in open(f).read().splitlines() if l.strip()]

    if label == "--report":
        if not rows:
            print("no phases recorded"); return
        start = float(rows[0][1]); prev = start
        print("phase            delta(s)  total(s)")
        for lbl, ts in rows:
            ts = float(ts)
            print("%-16s %7.1f %8.1f" % (lbl, ts - prev, ts - start)); prev = ts
        print("%-16s %7s %8.1f" % ("(total run)", "", prev - start))
        return

    now = time.time()
    with open(f, "a") as fh:
        fh.write("%s\t%.3f\n" % (label, now))
    if not rows:
        print("phase START '%s'  (t=0)" % label)
    else:
        start = float(rows[0][1]); prev = float(rows[-1][1])
        print("phase '%s'  +%.1fs (since '%s')  total %.1fs" % (label, now - prev, rows[-1][0], now - start))

if __name__ == "__main__":
    main()

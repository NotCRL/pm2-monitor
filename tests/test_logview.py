"""The log filters live in the page as pure functions; they are run here under node, exactly as shipped."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r"""
const view = (raw, f) => buildLogView(raw.join('\n'), Object.assign({query: '', levels: new Set(), context: 0, collapse: false}, f));
const texts = v => v.rows.map(r => r.gap ? '~gap~' : r.text + (r.count > 1 ? ' x' + r.count : ''));
const stack = ['INFO start', 'ERROR boom', '    at a.b(C.java:1)', 'Caused by: x', 'WARN careful', 'plain line'];
const out = {};
out.levelOfEach = annotateLog(stack).map(l => l.level);
out.onlyErrorsKeepsItsStackTrace = texts(view(stack, {levels: new Set(['error'])}));
out.errorsAndWarnings = texts(view(stack, {levels: new Set(['error', 'warn'])}));
out.searchIgnoresCase = texts(view(['Timeout while calling', 'all good', 'TIMEOUT again'], {query: 'timeOut'}));
out.hitsCount = view(['a', 'b', 'a'], {query: 'a'}).hits + '/' + view(['a', 'b', 'a'], {query: 'a'}).total;
const long = ['l0', 'l1', 'needle', 'l3', 'l4', 'l5', 'l6', 'l7', 'needle', 'l9'];
out.contextWithGap = texts(view(long, {query: 'needle', context: 1}));
out.contextRowsAreMarked = view(long, {query: 'needle', context: 1}).rows.filter(r => r.ctx).length;
out.noContextWithoutFilter = texts(view(['a', 'b'], {context: 5}));
out.collapseIgnoresTimestamps = texts(view(['2026-10-30 10:00:01 retry', '2026-10-30T10:00:02.5 retry', '[10:00:03] retry', 'done'], {collapse: true}));
out.collapseOnlyAdjacent = texts(view(['x', 'y', 'x'], {collapse: true}));
out.noFiltersShowsEverything = view(stack, {}).rows.length + '/' + view(stack, {}).hits;
out.emptyLog = view([], {}).rows.length;
out.noMatch = view(['abc'], {query: 'zzz'}).rows.length + '/' + view(['abc'], {query: 'zzz'}).hits;
out.javaAndNodeErrors = annotateLog(['java.lang.IllegalStateException: no', 'TypeError: x is not a function', 'fatal error', 'FATAL oops']).map(l => l.level);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page's JavaScript")
class LogViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        block = html.split("/* logview:start", 1)[1].split("*/", 1)[1].split("/* logview:end */", 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "logview_cases.js"
            script.write_text(block + HARNESS, encoding="utf-8")
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout)

    def test_levels_are_detected_and_stack_traces_follow_their_line(self):
        self.assertEqual(self.out["levelOfEach"], ["info", "error", "error", "error", "warn", None])

    def test_error_filter_keeps_the_whole_stack_trace(self):
        self.assertEqual(self.out["onlyErrorsKeepsItsStackTrace"], ["ERROR boom", "    at a.b(C.java:1)", "Caused by: x"])
        self.assertEqual(self.out["errorsAndWarnings"][-1], "WARN careful")

    def test_search_ignores_case_and_counts_hits(self):
        self.assertEqual(self.out["searchIgnoresCase"], ["Timeout while calling", "TIMEOUT again"])
        self.assertEqual(self.out["hitsCount"], "2/3")

    def test_context_adds_neighbours_and_marks_gaps(self):
        self.assertEqual(self.out["contextWithGap"], ["l1", "needle", "l3", "~gap~", "l7", "needle", "l9"])
        self.assertEqual(self.out["contextRowsAreMarked"], 4)
        self.assertEqual(self.out["noContextWithoutFilter"], ["a", "b"])

    def test_repeated_lines_collapse_even_with_different_timestamps(self):
        self.assertEqual(self.out["collapseIgnoresTimestamps"], ["2026-10-30 10:00:01 retry x3", "done"])
        self.assertEqual(self.out["collapseOnlyAdjacent"], ["x", "y", "x"])

    def test_edge_cases(self):
        self.assertEqual(self.out["noFiltersShowsEverything"], "6/6")
        self.assertEqual(self.out["emptyLog"], 0)
        self.assertEqual(self.out["noMatch"], "0/0")
        self.assertEqual(self.out["javaAndNodeErrors"], ["error", "error", None, "error"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Smoke tests for the entire-agent-hermes protocol binary. No network."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin", "entire-agent-hermes")


def run(subcmd, stdin="", args=(), env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    p = subprocess.run(
        [sys.executable, BIN] + list(subcmd) + list(args),
        input=stdin, capture_output=True, text=True, env=env, timeout=15,
    )
    return p


def jrun(subcmd, stdin_obj=None, args=(), env_extra=None):
    p = run(subcmd, json.dumps(stdin_obj) if stdin_obj is not None else "", args, env_extra)
    assert p.returncode == 0, "%s failed: %s" % (subcmd, p.stderr)
    return json.loads(p.stdout) if p.stdout.strip() else None


class Protocol(unittest.TestCase):
    def test_info(self):
        info = jrun(["info"])
        self.assertEqual(info["protocol_version"], 1)
        self.assertEqual(info["name"], "hermes")
        self.assertTrue(info["capabilities"]["hooks"])
        self.assertTrue(info["capabilities"]["transcript_analyzer"])

    def test_detect(self):
        self.assertIn("present", jrun(["detect"]))

    def test_get_session_id(self):
        self.assertEqual(jrun(["get-session-id"], {"session_id": "abc"})["session_id"], "abc")

    def test_session_paths(self):
        d = jrun(["get-session-dir"], args=["--repo-path", "/tmp/myrepo"])["session_dir"]
        self.assertTrue(d.endswith("tmp-myrepo-" + d.rsplit("-", 1)[-1]))
        f = jrun(["resolve-session-file"],
                 args=["--session-dir", d, "--session-id", "s1"])["session_file"]
        self.assertTrue(f.endswith("/s1.jsonl"))

    def test_parse_hook_mapping(self):
        payload = {"session_id": "s1", "transcript_path": "/tmp/s1.jsonl",
                   "user_message": "hi", "model": "m"}
        for hook, etype in [("session-start", 1), ("user-prompt-submit", 2),
                            ("stop", 3), ("session-end", 5)]:
            ev = jrun(["parse-hook", "--hook", hook], payload)
            self.assertEqual(ev["type"], etype)
            self.assertEqual(ev["session_id"], "s1")
        self.assertIsNone(jrun(["parse-hook", "--hook", "bogus"], payload))
        self.assertIsNone(jrun(["parse-hook", "--hook", "stop"], {"no_session": True}))

    def test_transcript_roundtrip(self):
        lines = [
            {"type": "user", "timestamp": "t", "message": {"content": "do it"}},
            {"type": "tool", "timestamp": "t", "tool_name": "write_file",
             "tool_input": {"path": "a.py"}},
            {"type": "tool", "timestamp": "t", "tool_name": "patch",
             "tool_input": {"path": "b.py"}},
            {"type": "assistant", "timestamp": "t",
             "message": {"content": [{"type": "text", "text": "done"}]}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(json.dumps(l) for l in lines) + "\n")
            path = f.name
        try:
            pos = jrun(["get-transcript-position"], args=["--path", path])
            self.assertEqual(pos["position"], 4)
            mf = jrun(["extract-modified-files"], args=["--path", path, "--offset", "0"])
            self.assertEqual(sorted(mf["files"]), ["a.py", "b.py"])
            self.assertEqual(mf["current_position"], 4)
            mf2 = jrun(["extract-modified-files"], args=["--path", path, "--offset", "3"])
            self.assertEqual(mf2["files"], [])
            pr = jrun(["extract-prompts"], args=["--session-ref", path, "--offset", "0"])
            self.assertEqual(pr["prompts"], ["do it"])
            sm = jrun(["extract-summary"], args=["--session-ref", path])
            self.assertTrue(sm["has_summary"])
            # chunk/reassemble roundtrip
            raw = open(path, "rb").read()
            ch = subprocess.run([sys.executable, BIN, "chunk-transcript", "--max-size", "40"],
                                input=raw, capture_output=True)
            self.assertEqual(ch.returncode, 0, ch.stderr)
            chunks = json.loads(ch.stdout)
            back = subprocess.run([sys.executable, BIN, "reassemble-transcript"],
                                  input=json.dumps(chunks).encode(), capture_output=True)
            self.assertEqual(back.stdout, raw)
        finally:
            os.unlink(path)

    def test_write_read_session(self):
        with tempfile.TemporaryDirectory() as td:
            ref = os.path.join(td, "sub", "s1.jsonl")
            session = {"session_id": "s1", "agent_name": "hermes",
                       "repo_path": "/tmp/myrepo", "session_ref": ref,
                       "start_time": "2026-10-11T00:00:00Z", "native_data": None,
                       "modified_files": ["a.py"], "new_files": [], "deleted_files": []}
            p = run(["write-session"], json.dumps(session))
            self.assertEqual(p.returncode, 0, p.stderr)
            got = jrun(["read-session"], {"session_id": "s1", "transcript_path": ref})
            self.assertEqual(got["modified_files"], ["a.py"])
            self.assertEqual(got["agent_name"], "hermes")

    def test_format_resume(self):
        self.assertEqual(
            jrun(["format-resume-command"], args=["--session-id", "abc"])["command"],
            "hermes --resume abc")


if __name__ == "__main__":
    unittest.main(verbosity=2)

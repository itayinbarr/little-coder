#!/usr/bin/env python3
"""A scriptable stand-in for the `pi` subprocess, for tests.

The real tests spawn pi and skip when node_modules/.bin/pi is absent, so none of
them exercise the JSONL event loop. EOF/deadline/crash behaviour cannot be
expressed against a real agent anyway: it needs a process that exits on cue.

Mode comes from FAKE_PI_MODE. Reads JSONL requests on stdin, emits JSONL on
stdout, exactly as rpc_client expects.
"""
import json, os, sys, time


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def read_prompt():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "prompt":
            return msg
    return None


def main():
    mode = os.environ.get("FAKE_PI_MODE", "clean")

    if mode == "exit_before_ack":
        sys.stderr.write("fake_pi: dying before ack\n")
        sys.stderr.flush()
        os._exit(3)

    msg = read_prompt()
    if msg is None:
        return
    rid = msg.get("id")

    if mode == "crash_after_ack":
        emit({"type": "response", "id": rid, "success": True})
        emit({"type": "agent_start"})
        sys.stderr.write("fake_pi: boom\n")
        sys.stderr.flush()
        os._exit(1)

    if mode == "hang_after_ack":
        emit({"type": "response", "id": rid, "success": True})
        emit({"type": "agent_start"})
        time.sleep(3600)

    if mode == "end_then_exit":
        # agent_end and EOF in the same breath -- the ordering hazard
        emit({"type": "response", "id": rid, "success": True})
        emit({"type": "turn_end"})
        emit({"type": "agent_end"})
        os._exit(0)

    if mode == "end_then_write":
        emit({"type": "response", "id": rid, "success": True})
        emit({"type": "turn_end"})
        emit({"type": "agent_end"})
        deadline = time.time() + 2
        i = 0
        while time.time() < deadline:
            with open(os.path.join(os.getcwd(), "late_write.txt"), "a") as fh:
                fh.write(f"{i}\n")
            i += 1
            time.sleep(0.2)
        emit({"type": "agent_settled"})
        time.sleep(30)
        return

    # default: clean single turn with one tool call
    emit({"type": "response", "id": rid, "success": True})
    emit({"type": "agent_start"})
    emit({"type": "message_update",
          "assistantMessageEvent": {"type": "text_delta", "delta": "hello"}})
    emit({"type": "tool_execution_start", "toolCallId": "t1", "toolName": "read", "args": {"path": "x"}})
    emit({"type": "tool_execution_end", "toolCallId": "t1", "toolName": "read",
          "result": {"content": [{"type": "text", "text": "ok"}]}, "isError": False})
    emit({"type": "turn_end"})
    emit({"type": "agent_end"})
    emit({"type": "agent_settled"})
    time.sleep(30)


if __name__ == "__main__":
    main()

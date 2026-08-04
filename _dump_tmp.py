import json, sys
from gw2_evtc_parser import read_zevtc_archive, PythonEvtcParser

stem = sys.argv[1]; inst = int(sys.argv[2])
raw = read_zevtc_archive(f"zevtc files/{stem}.zevtc")
p = PythonEvtcParser()
fight = next(p.parse(raw))
events = list(p.parse_events(raw))
origin = min(e.time_ms for e in events)
d = json.load(open(f".tooling/ei-out/{stem}_detailed_wvw_kill.json"))
aid = [a for a in fight.agents if a.instance_id == inst][0].id

evs = sorted([e for e in events
    if getattr(e,"skill_id",None)==718 and getattr(e,"target_agent_id",None)==aid
    and type(e).__name__=="BoonApplyEvent"], key=lambda e:e.time_ms)
print(f"=== inst {inst} {len(evs)} regen events ===")
for e in evs:
    print(f"{e.time_ms-origin:6d} {e.kind:13s} src={e.source_agent_id:5d} dur={e.duration_ms} stk={e.stack_id}")
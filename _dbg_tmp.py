import json
from gw2_evtc_parser import read_zevtc_archive, PythonEvtcParser

stem="20260125-001308"; inst=3089
raw = read_zevtc_archive(f"zevtc files/{stem}.zevtc")
p = PythonEvtcParser()
fight = next(p.parse(raw))
events = list(p.parse_events(raw))
origin = min(e.time_ms for e in events)
aid = [a for a in fight.agents if a.instance_id == inst][0].id
evs = sorted([e for e in events
    if getattr(e,"skill_id",None)==718 and getattr(e,"target_agent_id",None)==aid
    and type(e).__name__=="BoonApplyEvent"], key=lambda e:e.time_ms)
mapped=[]
for e in evs:
    mapped.append((e.time_ms-origin, e.kind, e.source_agent_id, e.duration_ms, e.stack_id))
print("events:")
for m in mapped: print(" ", m)

class SI:
    __slots__=("start","dur","src","sid")
    def __init__(s,start,dur,src,sid): s.start=start;s.dur=dur;s.src=src;s.sid=sid
    def shift(s,ss,ds):
        s.start+=ss; s.dur-=ds

def sim(heal):
    q=[]; waste=[]; gen=[]; prev=mapped[0][0]
    def sort_q(): q.sort(key=lambda x:-heal.get(x.src,0))
    def upd(tp):
        if not q or tp<=0: return
        a=q[0]; diff=tp; lo=0
        if a.dur<tp: diff=a.dur; lo=tp-diff
        if a.start<a.start+diff: gen.append((a.start,a.start+diff,a.src))
        a.shift(0,diff)
        for s in q[1:]: s.shift(diff,0)
        if a.dur==0: q.pop(0)
        upd(lo)
    for t,kind,src,dur,sid in mapped:
        upd(t-prev)
        if kind=="apply":
            it=SI(t,dur,src,sid)
            if len(q)<5:
                q.append(it); sort_q()
                q.insert(0,q.pop(q.index(it)))
            else:
                tr=q[-1]
                waste.append((tr.src,tr.dur,tr.start,tr.sid))
                q[q.index(tr)]=it; sort_q()
                q.insert(0,q.pop(q.index(it)))
        print(f" t={t} {kind} src={src} dur={dur} sid={sid} | q=", [(s.start,s.dur,s.src,s.sid) for s in q], "waste:",waste)
        prev=t
    upd(84982-prev)
    from collections import defaultdict
    pg=defaultdict(int);pw=defaultdict(int)
    for s,e,src in gen: pg[src]+=e-s
    for src,v,st,sid in waste: pw[src]+=v
    print("gen",dict(pg),"pw",dict(pw),"bar",sum(pg.values()))

for h in ({2507:1000,13126:999},{2507:999,13126:1000}):
    print("=== heal",h); sim(h)
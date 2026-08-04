import json, itertools
from gw2_evtc_parser import read_zevtc_archive, PythonEvtcParser

def read_events(stem, inst):
    raw = read_zevtc_archive(f"zevtc files/{stem}.zevtc")
    p = PythonEvtcParser()
    fight = next(p.parse(raw))
    events = list(p.parse_events(raw))
    origin = min(e.time_ms for e in events)
    aid = [a for a in fight.agents if a.instance_id == inst][0].id
    evs = sorted([e for e in events
        if getattr(e,"skill_id",None)==718 and getattr(e,"target_agent_id",None)==aid
        and type(e).__name__=="BoonApplyEvent"], key=lambda e:e.time_ms)
    return origin, aid, evs

class SI:
    __slots__=("start","dur","src","sid","ext")
    def __init__(s,start,dur,src,sid): s.start=start;s.dur=dur;s.src=src;s.sid=sid;s.ext=[]
    @property
    def total(s): return s.dur+sum(v for _,v in s.ext)
    def shift(s,ss,ds):
        s.start+=ss; s.dur-=ds
        if s.dur==0 and s.ext:
            s.src,s.dur=s.ext[0]; s.ext.pop(0)

def simulate(mapped, duration, heal):
    q=[]; waste=[]; gen=[]; no_sort=False; prev=mapped[0][0]
    def sort_q():
        if no_sort: return
        q.sort(key=lambda x:-heal.get(x.src,0))
    def activate(it):
        nonlocal no_sort
        no_sort=True
        q.remove(it)
        if q and q[0].total<50: q[0]=it
        else: q.insert(0,it)
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
            else:
                tr=q[-1]
                waste.append((tr.src,tr.dur,tr.start))
                for s_,v in tr.ext: waste.append((s_,v,tr.start))
                q[q.index(tr)]=it; sort_q()
            activate(it)
        prev=t
    upd(duration-prev)
    from collections import defaultdict
    pg=defaultdict(int);pw=defaultdict(int)
    for s,e,src in gen: pg[src]+=e-s
    for src,v,st in waste: pw[src]+=v
    return sum(pg.values()), dict(pg), dict(pw)

def main():
    stem="20260125-001308"
    d=json.load(open(f".tooling/ei-out/{stem}_detailed_wvw_kill.json"))
    dur=d['durationMS']
    for inst,exp in ((3089,44.757),(3232,43.852)):
        origin,aid,evs=read_events(stem,inst)
        mapped=[(e.time_ms-origin,e.kind,e.source_agent_id,e.duration_ms,e.stack_id) for e in evs]
        if inst==3232: mapped=[m for m in mapped if m[1]=="apply"]
        srcs=sorted(set(m[2] for m in mapped if m[1]=="apply"))
        print(f"--- inst {inst} srcs={srcs} n_evs={len(mapped)} ---")
        for combo in itertools.permutations(range(2)):
            heal={srcs[0]:1000-combo[0],srcs[1]:1000-combo[1]} if len(srcs)>1 else {srcs[0]:1000}
            bar,pg,pw=simulate(mapped,dur,heal)
            print(f"  heal={heal} bar={round(bar/dur*100,3)} (EI {exp}) gen={pg} pw={pw}")
        for pl in d['players']:
            if pl.get('instanceID')==inst:
                for bu in pl.get('buffUptimes',[]):
                    if bu.get('id')==718:
                        print("  EI uptime:",round(bu['buffData'][0]['uptime'],3))
                        print("  EI wasted:",bu['buffData'][0]['wasted'])
                        print("  EI states:",bu['states'])
main()
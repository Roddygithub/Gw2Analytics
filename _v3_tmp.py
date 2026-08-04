import json
from collections import defaultdict
from gw2_evtc_parser import read_zevtc_archive, PythonEvtcParser
from gw2_evtc_parser.parser import _compute_post_skills_offset, _EVENT_STRUCT_EVENTS_2025 as S

stem="20260125-001308"
raw = read_zevtc_archive(f"zevtc files/{stem}.zevtc")
off = _compute_post_skills_offset(raw, is_evtc_2025=True)
p = PythonEvtcParser()
fight = next(p.parse(raw))
aid = {a.instance_id:a.id for a in fight.agents}
events = list(p.parse_events(raw))
origin = min(e.time_ms for e in events)

def get_inst(inst):
    taid = next(a for a in fight.agents if a.instance_id==inst).id
    out=[]
    for c in range(off,len(raw)-64+1,64):
        t=S.unpack_from(raw,c)
        if t[6]==718 and t[2]==taid:
            out.append((t[0]-origin, t[3], t[1], t[19], bool(t[17]), t[15]))
    return sorted(out)

class SI:
    __slots__=("start","dur","src","sid","ext")
    def __init__(s,start,dur,src,sid): s.start=start;s.dur=dur;s.src=src;s.sid=sid;s.ext=[]
    @property
    def total(s): return s.dur+sum(v for _,v in s.ext)
    def shift(s,ss,ds):
        s.start+=ss; s.dur-=ds
        if s.dur==0 and s.ext: s.src,s.dur=s.ext[0]; s.ext.pop(0)

def simulate(mapped, duration, heal):
    q=[]; waste=[]; gen=[]; no_sort=False; prev=mapped[0][0]
    def sort_q():
        if not no_sort: q.sort(key=lambda x:-heal.get(x.src,0))
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
        gen.append((a.start,a.start+diff,a.src))
        a.shift(0,diff)
        for s in q[1:]: s.shift(diff,0)
        if a.dur==0: q.pop(0)
        upd(lo)
    for t,dur,src,sid,added,rmv in mapped:
        upd(t-prev)
        if rmv==0:  # apply
            it=SI(t,dur,src,sid)
            if len(q)<5: q.append(it)
            else:
                tr=q[-1]
                waste.append((tr.src,tr.dur))
                for s_,v in tr.ext: waste.append((s_,v))
                q[q.index(tr)]=it
            sort_q()
            if added: activate(it)
        prev=t
    upd(duration-prev)
    pg=defaultdict(int);pw=defaultdict(int)
    for s,e,src in gen: pg[src]+=e-s
    for src,v in waste: pw[src]+=v
    return sum(pg.values()), dict(pg), dict(pw)

dur=json.load(open(f".tooling/ei-out/{stem}_detailed_wvw_kill.json"))['durationMS']
for inst,exp in ((3089,44.757),(3232,43.852)):
    mapped=get_inst(inst)
    srcs=sorted({m[2] for m in mapped if m[4] is not None})
    print(f"--- inst {inst} n={len(mapped)} srcs={srcs} shields={[1 if m[4] else 0 for m in mapped]} ---")
    import itertools
    for combo in itertools.permutations(range(len(srcs))):
        heal={s:1000-r for s,r in zip(srcs,combo)}
        bar,pg,pw=simulate(mapped,dur,heal)
        if abs(bar/dur*100-exp)<=0.01:
            print(f"  MATCH heal={heal} bar={round(bar/dur*100,3)} pw={pw}")
    print("  EI:",exp,"states=[[0,0],[2905,1],[40940,0]]" if inst==3089 else "[[0,0],[2958,1],[40224,0]]")

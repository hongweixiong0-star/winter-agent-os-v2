"""Performance V2: recorded-frame analysis, not a counterfactual game simulator."""
from __future__ import annotations
import argparse, json, re, sys, time, types
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from winter_agent_v2.fishing_vision import FishingVision, detect_fishing
from winter_agent_v2.fishing_session import FishingSessionController


def read_frames(folder):
    payload=json.loads((folder/'run.json').read_text(encoding='utf-8')) if (folder/'run.json').exists() else {}
    timeline=payload.get('control_session',{}).get('timeline',[])
    result=[]
    for path in sorted((folder/'frames').glob('*.png')):
        index=int(re.search(r'\d+',path.stem)[0])
        if path.stem.startswith('f') and index>1140:
            continue
        at=timeline[index]['at'] if index<len(timeline) else index/20
        finger=timeline[index].get('finger_x') if index<len(timeline) else 360
        result.append((index,at,finger,np.asarray(Image.open(path).convert('RGB')),str(path)))
    return payload,result


def collision_proxy(state,x):
    if x is None or state.hook_y is None:
        return 0.
    return sum(max(0,1-(abs(x-o['x'])-o['w']/2-28)/100)*max(0,1-(o['y']-state.hook_y)/350)
               for o in state.obstacles if -20<=o['y']-state.hook_y<=280)


def evaluate(frames, params=None, legacy=None):
    vision=FishingVision()
    controller=legacy() if legacy else FishingSessionController(**(params or {}))
    rows, commands, risks=[],[],[]
    for index,at,finger,frame,path in frames:
        state=vision(frame,timestamp=at)
        observed=detect_fishing(frame,roi=(120,0,620,1280)) if legacy else state
        observed.finger_x=finger
        controller.set_frame(frame)
        command=controller(observed) if state.meta.get('gameplay') and not observed.lost else None
        dx=command.desired_x-finger if command and command.desired_x is not None and finger is not None else 0
        if state.meta.get('gameplay'):
            risks.append(collision_proxy(state,(state.line_x or 360)+np.clip(dx*.5,-28,28)))
            commands.append(dx)
        rows.append({'index':index,'timestamp':at,'source_frame':path,**state.to_dict(),
                     'gameplay':state.meta.get('gameplay'),'finger_x':finger,
                     'desired_x':getattr(command,'desired_x',None),
                     'phase':getattr(controller.last,'phase',None),
                     'servo_command':command.to_dict() if command else None})
    jerk=float(np.mean(np.abs(np.diff(commands)))) if len(commands)>1 else 0.
    stats={**vision.summary(),'collision_risk_proxy':float(np.mean(risks)) if risks else None,
           'command_variation_proxy':jerk,
           'fish_detections_per_gameplay_frame':sum(len(r['fish']) for r in rows if r['gameplay'])/max(1,vision.gameplay),
           **{k:v for k,v in controller.summary().items() if k!='decision_trace'}}
    return stats,rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'learning/fishing_performance_v2_replay')
    parser.add_argument('--baseline-controller',type=Path,required=True)
    args=parser.parse_args()
    module=types.ModuleType('winter_agent_v2.fishing_baseline')
    module.__package__='winter_agent_v2'
    sys.modules[module.__name__]=module
    ns=module.__dict__
    exec(compile(args.baseline_controller.read_text(encoding='utf-8'),str(args.baseline_controller),'exec'),ns)
    legacy=ns['FishingSessionController']
    runs=[ROOT/'dataset/raw/fishing_tournament'/n for n in ('run_20260929T231017','run_20260929T225731')]
    data=[read_frames(folder) for folder in runs]
    base=[evaluate(frames,legacy=legacy)[0] for payload,frames in data]
    candidates=[]
    for smoothing in (.25,.35,.55):
        for gain in (.6,.85):
            params=dict(smoothing=smoothing,line_gain=gain,hysteresis=.1,prediction_horizon=.6)
            stats=[evaluate(frames,params=params)[0] for payload,frames in data]
            candidates.append({'params':params,'runs':stats,
                'risk':float(np.mean([s['collision_risk_proxy'] for s in stats])),
                'variation':float(np.mean([s['command_variation_proxy'] for s in stats]))})
    baseline_risk=float(np.mean([s['collision_risk_proxy'] for s in base]))
    baseline_variation=float(np.mean([s['command_variation_proxy'] for s in base]))
    eligible=[c for c in candidates if c['risk']<=baseline_risk and c['variation']<=baseline_variation]
    best=min(eligible,key=lambda c:c['risk']+.005*c['variation']) if eligible else None
    args.output.mkdir(parents=True,exist_ok=True)
    chosen=best['params'] if best else {}
    reports=[]
    for folder,(payload,frames) in zip(runs,data):
        stats,rows=evaluate(frames,params=chosen)
        (args.output/(folder.name+'_timeline.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=1),encoding='utf-8')
        reports.append({'run':folder.name,'sampled_frames':len(frames),'metrics':stats,
                        'recorded_depth_m':payload.get('depth_m'),
                        'legacy_report_max_lost_streak':payload.get('control_session',{}).get('max_lost_streak')})
    report={'replay_runs':len(runs),'baseline':base,'candidates':candidates,'selected':best,
            'offline_non_degradation':best is not None,'runs':reports,
            'limitations':['Recorded frames are sampled, not a closed-loop simulator.',
                          'Risk and command variation are proxies; no depth or points gain is predicted.',
                          'Runtime unknown gameplay stats are not replaced with zero.',
                          'Original 137-frame lost streak includes post-game transition/result frames.']}
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    analysis=f'''# FISHING_V1_FAILURE_ANALYSIS

Source: run_20260929T231017, original 460 tick rows, 31 saved frames.
Recorded baseline: depth 54m, points 150→190 (+40), first line 3.03s, max lost streak 137.
The archived standalone tool spent 26 calibration ticks. Current production already uses zero;
the replay compares the pre-V2 production controller, not that obsolete calibration setting.
The original water crop missed shallow/scrolling hook positions. That crop was already enlarged
in the production sprint; Performance V2 retains it and adds continuity/confidence, not another executor.
The long tail includes surface and result frames: classify these separately before computing coverage.
Warm-only blobs omit the grey/green fish shown in t00150. Classifying hazards by their vertical
position cannot distinguish a pufferfish below the hook from an edible fish.
The recorded camera pins the descending hook near the top. Retrieval moves it DOWN the screen;
the old controller interpreted that sign backwards. V2 confirms the sustained turnaround once.

Current-controller proxy risk={baseline_risk:.4f}, command variation={baseline_variation:.4f}.
Pareto-eligible candidate: {json.dumps(best['params'] if best else None)}.
See summary.json and per-run timelines for actual sampled positions, fish/hazard boxes and commands.
No counterfactual score/depth claim is made. Sparse frames cannot establish full-rate reacquisition latency
or exact collision count. Those remain live-validation measurements.
'''
    (args.output/'FISHING_V1_FAILURE_ANALYSIS.md').write_text(analysis,encoding='utf-8')
    print(json.dumps({'baseline_risk':baseline_risk,'baseline_variation':baseline_variation,
                      'selected':best,'runs':reports},ensure_ascii=True))
    return 0 if best else 1

if __name__=='__main__':
    raise SystemExit(main())

import cv2
import numpy as np
from winter_agent_v2.fishing_vision import FishingVision, FishingFrame
from winter_agent_v2.fishing_session import FishingSessionController, Phase


def scene(x=350, hook_y=650):
    image=np.full((1280,720,3),(10,120,180),dtype=np.uint8)
    cv2.line(image,(x,0),(x,hook_y),(10,10,10),3)
    cv2.circle(image,(x,hook_y),10,(90,240,60),-1)
    cv2.ellipse(image,(230,950),(40,15),0,0,360,(160,165,160),-1)
    cv2.circle(image,(540,950),60,(230,175,50),-1)
    return image


def test_grey_fish_is_not_missed_and_round_puffer_is_never_food():
    state=FishingVision()(scene(),timestamp=0)
    assert any(abs(f['x']-230)<20 for f in state.fish)
    assert any(abs(o['x']-540)<30 for o in state.obstacles)
    assert not any(abs(f['x']-540)<30 for f in state.fish)


def test_fish_occlusion_prediction_is_bounded_and_not_an_actual_detection():
    vision=FishingVision()
    vision(scene(),timestamp=0)
    vision(scene(),timestamp=.05)
    image=scene()
    image[925:975,185:275]=(10,120,180)
    for at in (.1,.15,.2):
        state=vision(image,timestamp=at)
        assert not state.fish
        assert state.meta['predicted_fish'][0]['predicted']
    assert not vision(image,timestamp=.25).meta['predicted_fish']


def test_unrelated_dark_column_does_not_replace_hook_aligned_track():
    vision=FishingVision()
    assert abs(vision(scene(),timestamp=0).line_x-350)<5
    image=scene()
    cv2.rectangle(image,(580,0),(587,1279),(0,0,0),-1)
    state=vision(image,timestamp=.05)
    assert abs(state.line_x-350)<10


def test_missing_pixels_remain_missing_and_reacquisition_is_measured():
    vision=FishingVision()
    vision(scene(),timestamp=0)
    blank=np.full((1280,720,3),(10,120,180),dtype=np.uint8)
    assert vision(blank,timestamp=.05).lost
    assert vision(scene(),timestamp=.1).found
    assert vision.summary()['reacquire_success']==1
    assert vision.summary()['reacquire_latency_ms']==50


def test_result_transition_is_not_counted_as_gameplay_loss():
    vision=FishingVision()
    vision(scene(),timestamp=0)
    state=vision(np.zeros((1280,720,3),dtype=np.uint8),timestamp=.05)
    assert not state.meta['gameplay']
    assert vision.summary()['lost_frame_ratio']==0


def test_surface_countdown_does_not_authorize_underwater_control():
    image=scene()
    image[:800]=(120,130,140)  # observed pre-cast scene: sky/ice above the water
    cv2.putText(image,'3',(330,630),cv2.FONT_HERSHEY_SIMPLEX,4,(255,255,255),8)
    state=FishingVision()(image,timestamp=0)
    assert not state.found and not state.meta['gameplay']


def test_performance_metrics_survive_existing_ledger_roundtrip():
    from winter_agent_v2.fishing_state import FishingRun
    row={'run_id':'v2','role_key':'ROLE_A','at':'2026-09-30T11:00:00Z',
         'bait_cost':1,'points_before':150,'points_after':190,
         'performance':{'control_coverage':.98,'collision_count':None}}
    run=FishingRun.from_mapping(row)
    assert run.points_gain==40
    assert run.to_mapping()['performance']==row['performance']


def test_ascent_is_confirmed_after_camera_turnaround_and_never_flaps():
    controller=FishingSessionController()
    for i,y in enumerate([600,400,200]+[200]*7+[230,260,300,350,400,450,500,550,600]):
        state=FishingFrame(found=True,lost=False,line_x=350,hook_x=350,hook_y=y,finger_x=350,
                           meta={'timestamp':i*.05})
        controller(state)
    assert controller.phase is Phase.ASCENDING
    for i in range(12):
        controller(FishingFrame(found=True,lost=False,line_x=350,hook_y=100,finger_x=350,
                                meta={'timestamp':2+i*.05}))
    assert controller.phase is Phase.ASCENDING
    assert controller.phase_switch_count==2  # READY→DESCENDING→ASCENDING


def test_smoothing_momentum_does_not_steer_into_visible_hazard():
    controller=FishingSessionController()
    controller._smoothed_target=500
    state=FishingFrame(found=True,lost=False,line_x=350,hook_y=650,finger_x=350,
                       obstacles=[{'x':430,'y':700,'w':70,'h':70}])
    command=controller(state)
    assert command.desired_x <= 350

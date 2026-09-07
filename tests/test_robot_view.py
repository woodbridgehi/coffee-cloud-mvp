from app.robot_view import public_robot_view
from app.live_progress import merge_progress


def test_public_plan_whitelists_metadata_and_keeps_frozen_durations():
    plan=[{"stepId":"milk","stepName":"加入鲜奶","stepIndex":0,"durationSeconds":12.34,
           "authToken":"private", "visual":{"version":1,"actions":["milk"],"private":"secret",
           "materials":[{"materialId":"milk","name":"鲜奶","amount":180,"unit":"ml","onHand":900,"cost":4}]}}]
    view=public_robot_view(plan)
    assert view["steps"][0]["durationSeconds"] == 12.34
    assert view["steps"][0]["visual"]["materials"] == [{"materialId":"milk","name":"鲜奶","amount":180,"unit":"ml"}]
    assert 'private' not in repr(view) and 'secret' not in repr(view) and 'onHand' not in repr(view)


def test_old_or_invalid_device_plan_does_not_offer_misleading_3d():
    assert public_robot_view(None) is None
    assert public_robot_view([{"stepId":"brew","durationSeconds":4}]) is None
    assert public_robot_view([{"visual":{"version":1,"actions":[{}]},"durationSeconds":4}]) is None
    assert public_robot_view([{"visual":{"version":1,"actions":["brew"],"materials":True},"durationSeconds":4}]) is None


def test_ephemeral_progress_preserves_visual_plan_and_hold_wins():
    view={"version":1,"steps":[{"stepId":"brew"}]}
    original={"deviceId":"d1","status":"MAKING","production":{"taskId":"t1","status":"EXECUTING",
              "deviceRevision":1,"robotView":view,"overallProgress":0.1,"stepProgress":0.1}}
    event={"deviceId":"d1","payload":{"taskId":"t1","taskRevision":2,"stepId":"brew","stepProgress":0.7}}
    result=merge_progress(original,event)
    assert result["production"]["robotView"] == view
    assert result["production"]["stepProgress"] == 0.7
    result["status"]='HOLD'
    assert merge_progress(result,{**event,"payload":{**event["payload"],"taskRevision":3}}) is result

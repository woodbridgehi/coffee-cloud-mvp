from app.failure_info import failure_info


def test_old_ack_failure_has_human_reason_and_internal_diagnostics_only():
    order = {'status':'FAILED','failure_code':'COMPILED_RECIPE_MISMATCH','failure_message':'制作失败'}
    job = {'task_id':'t1','failure_json':{'code':'COMPILED_RECIPE_MISMATCH','details':{'requestedDigest':None,'installedDigest':'sha256:abc','accessToken':'secret'}}}
    public = failure_info(order,job)
    assert '指纹' in public['message']
    assert set(public) == {'code','message'}
    internal = failure_info(order,job,internal=True)
    assert internal['taskId']=='t1'
    assert internal['details']=={'requestedDigest':None,'installedDigest':'sha256:abc'}
    assert internal['suggestion']


def test_unknown_and_missing_failure_reasons_do_not_disappear():
    assert failure_info({'status':'FAILED'})['code']=='PRODUCTION_FAILED'
    assert failure_info({'status':'FAILED'}, {'failure_json':{'code':{},'message':[]}})['code']=='PRODUCTION_FAILED'
    assert failure_info({'status':'READY'}) is None
    detail = failure_info({'status':'REFUNDED','failure_code':'POUR_FAILED'},
        {'failure_json':{'message':'奶泡杯倾倒失败','stepId':'latte-art','stepName':'螺旋拉花'}},internal=True)
    assert detail['message']=='奶泡杯倾倒失败'
    assert detail['stepName']=='螺旋拉花'

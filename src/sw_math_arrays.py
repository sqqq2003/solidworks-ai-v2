"""Typed SAFEARRAY bridge for SW2022 gen_py. No COM imports during discovery."""
import math


def double_array(values, length):
    values=tuple(values)
    if len(values)!=length or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        raise ValueError('finite double array of length '+str(length)+' required')
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,tuple(float(v) for v in values))


def create_point(utility,coordinates):
    point=utility.CreatePoint(double_array(coordinates,3))
    if point is None:raise RuntimeError('CreatePoint failed')
    return point


def create_transform(utility,array):
    transform=utility.CreateTransform(double_array(array,16))
    if transform is None:raise RuntimeError('CreateTransform failed')
    readback=tuple(transform.ArrayData)
    if len(readback)!=16 or any(not math.isclose(a,b,abs_tol=1e-12,rel_tol=1e-12) for a,b in zip(readback,array)):
        raise RuntimeError('CreateTransform readback differs from input')
    return transform


def oracle(app, cases):
    from sw_session import require_model_write
    lease=require_model_write()
    import pythoncom,win32com.client
    import solidworks_generator as sw
    bound,_=sw._connect_task_solidworks(lease,win32com,pythoncom)
    if int(bound.GetProcessID())!=int(app.GetProcessID()):raise RuntimeError('foreign SW application refused')
    utility=app.GetMathUtility()
    results=[]
    for case in cases:
        transform=create_transform(utility,case['transform'])
        point=create_point(utility,case['point']).MultiplyTransform(transform)
        if point is None:raise RuntimeError('MultiplyTransform returned no point')
        xyz=tuple(point.ArrayData)  # IMathPoint exposes ArrayData, not X/Y properties.
        predicted=sw._transform_to_sketch(case['transform'],case['point'])
        deviation=max(abs(predicted[i]-xyz[i]) for i in range(2))
        results.append({'native_xyz_m':xyz,'predicted_xy_m':predicted,'max_dev_m':deviation})
    return {'oracle_ok':bool(results) and all(r['max_dev_m']<=1e-10 for r in results),
            'cases':results,'scope':'math_transform_only','p248_acceptance':'unverified','cad_written':False}

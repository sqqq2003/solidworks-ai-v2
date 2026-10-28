"""Read analytic cylindrical surfaces; this does not identify holes or certify cuts."""
import math


def cylindrical_surface_inventory(part, sw, module):
    records = []
    bodies = part.GetBodies2(sw.SW_BODY_TYPE_SOLID, False) or ()
    if not bodies:
        raise RuntimeError('cylinder inspection requires solid bodies')
    for body_index, raw_body in enumerate(bodies):
        body = sw._as_interface(module, raw_body, 'IBody2')
        faces = body.GetFaces()
        if not faces:
            raise RuntimeError('solid body faces unavailable')
        for face_index, raw_face in enumerate(faces):
            face = sw._as_interface(module, raw_face, 'IFace2')
            surface = sw._as_interface(module, sw._com_read(face, 'GetSurface'), 'ISurface')
            if not sw._com_read(surface, 'IsCylinder'):
                continue
            params = list(sw._com_read(surface, 'CylinderParams'))
            if len(params) != 7 or not all(math.isfinite(v) for v in params) or params[6] <= 0:
                raise RuntimeError('invalid native cylinder parameters')
            records.append({'body_index': body_index, 'face_index': face_index,
                            'axis_point_mm': [v * 1000 for v in params[:3]],
                            'axis_direction': params[3:6], 'radius_mm': params[6] * 1000,
                            'diameter_mm': params[6] * 2000})
    return {'scope': 'analytic_cylindrical_faces_not_hole_or_slot_acceptance',
            'faces': records, 'geometry_verified': False}

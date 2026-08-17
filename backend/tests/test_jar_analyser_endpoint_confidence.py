"""Stage 5 — honest confidence & opacity flagging (endpoint_confidence.py)."""
from app.services.jar_analyser.endpoint_confidence import refine_endpoint_confidence


def _ep(confidence="HIGH", return_type=None, request_body=None):
    return {"confidence": confidence, "return_type": return_type, "request_body": request_body}


def test_resolved_dto_return_type_keeps_high_confidence():
    eps = [_ep(return_type={"java_type": "com.x.CustomerDto", "simple_type": "CustomerDto"})]
    refine_endpoint_confidence(eps, [{"simple_name": "CustomerDto"}])
    assert eps[0]["payload_shape_known"] is True
    assert eps[0]["confidence"] == "HIGH"


def test_void_return_with_no_body_is_known():
    eps = [_ep(return_type={"java_type": "void", "simple_type": "void"})]
    refine_endpoint_confidence(eps, [])
    assert eps[0]["payload_shape_known"] is True
    assert eps[0]["confidence"] == "HIGH"


def test_generic_wrapper_return_type_is_opaque_and_downgrades_high_to_medium():
    eps = [_ep(return_type={"java_type": "org.springframework.http.ResponseEntity", "simple_type": "ResponseEntity"})]
    refine_endpoint_confidence(eps, [{"simple_name": "CustomerDto"}])
    assert eps[0]["payload_shape_known"] is False
    assert eps[0]["confidence"] == "MEDIUM"


def test_raw_object_request_body_is_opaque():
    eps = [_ep(request_body={"java_type": "java.lang.Object", "simple_type": "Object"})]
    refine_endpoint_confidence(eps, [])
    assert eps[0]["payload_shape_known"] is False
    assert eps[0]["confidence"] == "MEDIUM"


def test_both_directions_opaque_downgrades_to_low():
    eps = [_ep(
        return_type={"java_type": "java.util.Map", "simple_type": "Map"},
        request_body={"java_type": "java.lang.Object", "simple_type": "Object"},
    )]
    refine_endpoint_confidence(eps, [])
    assert eps[0]["payload_shape_known"] is False
    assert eps[0]["confidence"] == "LOW"


def test_unresolvable_external_type_is_opaque():
    eps = [_ep(return_type={"java_type": "com.external.Widget", "simple_type": "Widget"})]
    refine_endpoint_confidence(eps, [{"simple_name": "CustomerDto"}])
    assert eps[0]["payload_shape_known"] is False


def test_well_known_scalar_return_type_is_resolved():
    eps = [_ep(return_type={"java_type": "java.lang.String", "simple_type": "String"})]
    refine_endpoint_confidence(eps, [])
    assert eps[0]["payload_shape_known"] is True
    assert eps[0]["confidence"] == "HIGH"


def test_medium_base_confidence_not_upgraded_by_resolved_payload():
    eps = [_ep(confidence="MEDIUM", return_type={"java_type": "java.lang.String", "simple_type": "String"})]
    refine_endpoint_confidence(eps, [])
    assert eps[0]["confidence"] == "MEDIUM"


def test_array_of_known_dto_is_resolved():
    eps = [_ep(return_type={"java_type": "com.x.CustomerDto[]", "simple_type": "CustomerDto[]"})]
    refine_endpoint_confidence(eps, [{"simple_name": "CustomerDto"}])
    assert eps[0]["payload_shape_known"] is True

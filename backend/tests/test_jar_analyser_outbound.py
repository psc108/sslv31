"""Outbound integration discovery (Feign/@Value) and outbound call-site
response/error-handling analysis (Sections 38-39)."""
from app.services.jar_analyser.classfile import ClassInfo, FieldInfo, AnnotationInfo, AnnotationElement
from app.services.jar_analyser.outbound_integrations import (
    extract_outbound_integrations, FEIGN_CLIENT, VALUE_ANNOTATION,
)
from app.services.jar_analyser.outbound_call_analysis import extract_outbound_call_sites


# ---------------------------------------------------------------------------
# outbound_integrations.py
# ---------------------------------------------------------------------------

def _class_with_annotations(anns, class_name: str = "com/x/VraClient") -> ClassInfo:
    return ClassInfo(
        class_name=class_name, superclass=None, interfaces=[],
        annotations=anns, methods=[], fields=[], class_file_version=61,
    )


def _class_with_field(f: FieldInfo, class_name: str = "com/x/PaymentService") -> ClassInfo:
    return ClassInfo(
        class_name=class_name, superclass=None, interfaces=[],
        annotations=[], methods=[], fields=[f], class_file_version=61,
    )


def test_feign_client_with_literal_url():
    ann = AnnotationInfo(FEIGN_CLIENT, elements=[
        AnnotationElement("name", "vraClient"), AnnotationElement("url", "https://vra.example.com/api"),
    ])
    results = extract_outbound_integrations([_class_with_annotations([ann])], {})
    assert len(results) == 1
    oi = results[0]
    assert oi.kind == "feign_client"
    assert oi.class_name == "com.x.VraClient"
    assert oi.target == "vraClient"
    assert oi.raw_value == "https://vra.example.com/api"
    assert oi.config_key is None
    assert oi.resolved_value == "https://vra.example.com/api"


def test_feign_client_name_only_no_url_still_reported():
    ann = AnnotationInfo(FEIGN_CLIENT, elements=[AnnotationElement("name", "inventory-service")])
    results = extract_outbound_integrations([_class_with_annotations([ann])], {})
    assert len(results) == 1
    assert results[0].target == "inventory-service"
    assert results[0].config_key is None


def test_feign_client_url_placeholder_resolved_from_config():
    ann = AnnotationInfo(FEIGN_CLIENT, elements=[
        AnnotationElement("name", "vraClient"), AnnotationElement("url", "${vra.api.url}"),
    ])
    results = extract_outbound_integrations(
        [_class_with_annotations([ann])], {"vra.api.url": "https://vra.internal:8443"},
    )
    oi = results[0]
    assert oi.config_key == "vra.api.url"
    assert oi.raw_value == "${vra.api.url}"
    assert oi.resolved_value == "https://vra.internal:8443"


def test_feign_client_url_placeholder_falls_back_to_inline_default():
    ann = AnnotationInfo(FEIGN_CLIENT, elements=[
        AnnotationElement("name", "vraClient"), AnnotationElement("url", "${vra.api.url:https://default.vra}"),
    ])
    results = extract_outbound_integrations([_class_with_annotations([ann])], {})
    assert results[0].resolved_value == "https://default.vra"


def test_feign_client_value_attribute_used_as_name_fallback():
    ann = AnnotationInfo(FEIGN_CLIENT, elements=[AnnotationElement("value", "catalog-service")])
    results = extract_outbound_integrations([_class_with_annotations([ann])], {})
    assert results[0].target == "catalog-service"


def test_non_feign_class_annotation_ignored():
    ann = AnnotationInfo("Lorg/springframework/stereotype/Component;", elements=[])
    results = extract_outbound_integrations([_class_with_annotations([ann])], {})
    assert results == []


def test_value_field_with_url_key_included():
    ann = AnnotationInfo(VALUE_ANNOTATION, elements=[AnnotationElement("value", "${payment.gateway.url}")])
    f = FieldInfo(name="gatewayUrl", descriptor="Ljava/lang/String;", annotations=[ann])
    results = extract_outbound_integrations([_class_with_field(f)], {"payment.gateway.url": "https://pay.example"})
    assert len(results) == 1
    oi = results[0]
    assert oi.kind == "config_value"
    assert oi.target == "gatewayUrl"
    assert oi.config_key == "payment.gateway.url"
    assert oi.resolved_value == "https://pay.example"


def test_value_field_with_non_url_key_excluded():
    ann = AnnotationInfo(VALUE_ANNOTATION, elements=[AnnotationElement("value", "${app.retry.count}")])
    f = FieldInfo(name="retryCount", descriptor="I", annotations=[ann])
    results = extract_outbound_integrations([_class_with_field(f)], {})
    assert results == []


def test_value_field_literal_non_placeholder_excluded():
    # No ${...} placeholder means _placeholder_key finds nothing, so this is
    # excluded even though "host" itself matches the url|uri|host|address heuristic —
    # the key must come from a placeholder expression, not the raw literal.
    ann = AnnotationInfo(VALUE_ANNOTATION, elements=[AnnotationElement("value", "host")])
    f = FieldInfo(name="hostLiteral", descriptor="Ljava/lang/String;", annotations=[ann])
    results = extract_outbound_integrations([_class_with_field(f)], {})
    assert results == []


def test_value_field_with_no_value_element_excluded():
    ann = AnnotationInfo(VALUE_ANNOTATION, elements=[])
    f = FieldInfo(name="unused", descriptor="Ljava/lang/String;", annotations=[ann])
    results = extract_outbound_integrations([_class_with_field(f)], {})
    assert results == []


def test_multiple_classes_aggregated_in_order():
    ann1 = AnnotationInfo(FEIGN_CLIENT, elements=[AnnotationElement("name", "svc-a")])
    ann2 = AnnotationInfo(FEIGN_CLIENT, elements=[AnnotationElement("name", "svc-b")])
    classes = [
        _class_with_annotations([ann1], class_name="com/x/AClient"),
        _class_with_annotations([ann2], class_name="com/x/BClient"),
    ]
    results = extract_outbound_integrations(classes, {})
    assert [r.target for r in results] == ["svc-a", "svc-b"]


# ---------------------------------------------------------------------------
# outbound_call_analysis.py
# ---------------------------------------------------------------------------

def test_jaxrs_call_site_response_type_status_check_and_throw():
    source = """
public class CatalogClient {
    public RateCardDto getRateCard(String id) {
        Response response = this.rateCardWebTarget.path(id).request(MediaType.APPLICATION_JSON).get();
        if (response.getStatus() == Response.Status.NOT_FOUND.getStatusCode()) {
            throw new RateCardNotFoundException(id);
        }
        return response.readEntity(RateCardDto.class);
    }
}
"""
    sites = extract_outbound_call_sites(source)
    assert len(sites) == 1
    site = sites[0]
    assert site.call_type == "jaxrs_client"
    assert site.method_name == "getRateCard"
    assert site.response_type == "RateCardDto"
    assert site.status_checks == ["== NOT_FOUND"]
    assert site.thrown_exceptions == ["RateCardNotFoundException"]
    assert site.caught_exceptions == []


def test_resttemplate_call_site_response_type_from_trailing_class_literal():
    source = """
public class PricingClient {
    public PriceDto getPrice(String sku) {
        return restTemplate.getForObject(url, PriceDto.class);
    }
}
"""
    sites = extract_outbound_call_sites(source)
    assert len(sites) == 1
    assert sites[0].call_type == "resttemplate"
    assert sites[0].method_name == "getPrice"
    assert sites[0].response_type == "PriceDto"


def test_webclient_call_site_response_type_from_body_to_mono():
    source = """
public class NotifyClient {
    public Mono<AckDto> notify(Payload p) {
        return webClient.post().uri("/notify").bodyValue(p).retrieve().bodyToMono(AckDto.class);
    }
}
"""
    sites = extract_outbound_call_sites(source)
    assert len(sites) == 1
    assert sites[0].call_type == "webclient"
    assert sites[0].response_type == "AckDto"


def test_call_site_with_try_catch_multi_catch():
    source = """
public class LegacyClient {
    public String call() {
        try {
            return restTemplate.getForObject(url, String.class);
        } catch (RestClientException | IOException e) {
            throw new IntegrationException("failed", e);
        }
    }
}
"""
    sites = extract_outbound_call_sites(source)
    assert len(sites) == 1
    site = sites[0]
    assert site.caught_exceptions == ["RestClientException", "IOException"]
    assert site.thrown_exceptions == ["IntegrationException"]


def test_call_site_with_no_enclosing_method_has_null_method_name():
    source = 'restTemplate.getForObject("http://x", String.class);'
    sites = extract_outbound_call_sites(source)
    assert len(sites) == 1
    assert sites[0].method_name is None
    assert sites[0].response_type == "String"


def test_multiple_call_sites_across_methods_all_found():
    source = """
public class MultiClient {
    public String a() {
        return restTemplate.getForObject(urlA, String.class);
    }
    public String b() {
        return restTemplate.getForObject(urlB, String.class);
    }
}
"""
    sites = extract_outbound_call_sites(source)
    assert len(sites) == 2
    assert [s.method_name for s in sites] == ["a", "b"]


def test_response_type_via_parameterized_type_reference():
    source = """
public class ListClient {
    public List<ItemDto> getItems() {
        return restTemplate.exchange(url, HttpMethod.GET, null,
            new ParameterizedTypeReference<List<ItemDto>>() {}).getBody();
    }
}
"""
    sites = extract_outbound_call_sites(source)
    assert len(sites) == 1
    assert sites[0].response_type == "List<ItemDto>"


def test_no_call_sites_when_no_known_pattern_present():
    source = """
public class NotAnOutboundCall {
    public void doNothing() {
        System.out.println("hello");
    }
}
"""
    assert extract_outbound_call_sites(source) == []

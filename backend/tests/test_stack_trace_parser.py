"""Java stack-trace / log-blob parsing into an exception chain."""
from app.services.stack_trace_parser import extract_stack_traces


def test_single_exception_with_header_and_frames():
    text = """java.lang.NullPointerException: Cannot invoke "String.length()" because "s" is null
\tat com.dxc.ecs.fulfillment.service.ServiceDesignService.build(ServiceDesignService.java:42)
\tat com.dxc.ecs.fulfillment.controller.FulfillmentController.create(FulfillmentController.java:88)
"""
    blocks = extract_stack_traces(text)
    assert len(blocks) == 1
    b = blocks[0]
    assert b.kind == "root"
    assert b.exception_class == "java.lang.NullPointerException"
    assert b.message == 'Cannot invoke "String.length()" because "s" is null'
    assert len(b.frames) == 2
    assert b.frames[0].class_name == "com.dxc.ecs.fulfillment.service.ServiceDesignService"
    assert b.frames[0].method_name == "build"
    assert b.frames[0].file_name == "ServiceDesignService.java"
    assert b.frames[0].line_number == 42
    assert b.frames[0].is_native is False


def test_headerless_frames_only_block():
    # Grounded against a real example the user pasted where grep had
    # trimmed the "ExceptionClass: message" line off before the frames.
    text = """\tat com.dxc.ecs.customers.service.ContractService.lookup(ContractService.java:120)
\tat com.dxc.ecs.customers.controller.ContractResource.get(ContractResource.java:55)
"""
    blocks = extract_stack_traces(text)
    assert len(blocks) == 1
    assert blocks[0].kind == "root"
    assert blocks[0].exception_class is None
    assert blocks[0].message is None
    assert len(blocks[0].frames) == 2


def test_caused_by_chain():
    text = """java.lang.RuntimeException: outer failure
\tat com.x.A.a(A.java:1)
Caused by: java.sql.SQLException: connection refused
\tat com.x.B.b(B.java:2)
\tat com.x.C.c(C.java:3)
"""
    blocks = extract_stack_traces(text)
    assert len(blocks) == 2
    assert blocks[0].kind == "root"
    assert blocks[0].exception_class == "java.lang.RuntimeException"
    assert blocks[1].kind == "caused_by"
    assert blocks[1].exception_class == "java.sql.SQLException"
    assert blocks[1].message == "connection refused"
    assert len(blocks[1].frames) == 2


def test_suppressed_exception():
    text = """java.lang.Exception: primary
\tat com.x.A.a(A.java:1)
\tSuppressed: java.io.IOException: close failed
\t\tat com.x.B.close(B.java:9)
"""
    blocks = extract_stack_traces(text)
    assert len(blocks) == 2
    assert blocks[1].kind == "suppressed"
    assert blocks[1].exception_class == "java.io.IOException"
    assert blocks[1].message == "close failed"


def test_more_frames_marker_ignored():
    text = """java.lang.RuntimeException: outer
\tat com.x.A.a(A.java:1)
Caused by: java.lang.Exception: inner
\tat com.x.B.b(B.java:2)
\t... 5 more
"""
    blocks = extract_stack_traces(text)
    assert len(blocks) == 2
    assert len(blocks[1].frames) == 1


def test_native_method_frame():
    text = """java.lang.UnsatisfiedLinkError: no foo in java.library.path
\tat com.x.Native.load(Native Method)
"""
    blocks = extract_stack_traces(text)
    frame = blocks[0].frames[0]
    assert frame.is_native is True
    assert frame.file_name is None
    assert frame.line_number is None


def test_unknown_source_frame():
    text = """java.lang.Exception: dynamically generated
\tat com.x.Proxy.invoke(Unknown Source)
"""
    blocks = extract_stack_traces(text)
    frame = blocks[0].frames[0]
    assert frame.file_name is None
    assert frame.line_number is None
    assert frame.is_native is False


def test_jpms_module_qualified_frame_parsed():
    # Standard since Java 9 for JDK-internal frames - the "java.base/" module
    # prefix must be dropped, not folded into the class name.
    text = """java.lang.NullPointerException: boom
\tat java.base/java.lang.reflect.Method.invoke(Method.java:568)
\tat app//com.example.Foo.bar(Foo.java:10)
"""
    frames = extract_stack_traces(text)[0].frames
    assert frames[0].class_name == "java.lang.reflect.Method"
    assert frames[0].method_name == "invoke"
    assert frames[1].class_name == "com.example.Foo"
    assert frames[1].method_name == "bar"


def test_logback_classpath_suffix_ignored():
    text = """java.lang.Exception: boom
\tat com.x.A.a(A.java:1) ~[fulfillment.jar:2.6.9]
"""
    blocks = extract_stack_traces(text)
    frame = blocks[0].frames[0]
    assert frame.file_name == "A.java"
    assert frame.line_number == 1


def test_interleaved_log_noise_ignored():
    text = """2026-08-13 10:15:22.001 ERROR [http-nio-8080-exec-3] c.d.e.f.FulfillmentController - Unhandled error
java.lang.IllegalStateException: bad state
\tat com.x.A.a(A.java:1)
2026-08-13 10:15:22.002 WARN  [http-nio-8080-exec-3] c.d.e.f.FulfillmentController - continuing
\tat com.x.B.b(B.java:2)
"""
    blocks = extract_stack_traces(text)
    assert len(blocks) == 1
    assert blocks[0].exception_class == "java.lang.IllegalStateException"
    assert len(blocks[0].frames) == 2


def test_exception_with_no_message():
    text = """java.lang.NullPointerException
\tat com.x.A.a(A.java:1)
"""
    blocks = extract_stack_traces(text)
    assert blocks[0].exception_class == "java.lang.NullPointerException"
    assert blocks[0].message is None


def test_empty_text_returns_no_blocks():
    assert extract_stack_traces("") == []
    assert extract_stack_traces("   \n  \n") == []


def test_plain_log_with_no_stack_trace_returns_no_blocks():
    text = """2026-08-13 10:15:22.001 INFO  [main] c.d.e.f.App - Started application in 3.2 seconds
"""
    assert extract_stack_traces(text) == []


# ---------------------------------------------------------------------------
# is_application_frame
# ---------------------------------------------------------------------------

def test_own_code_frame_is_application_frame():
    text = """java.lang.NullPointerException: boom
\tat com.dxc.ecs.fulfillment.service.ServiceDesignService.build(ServiceDesignService.java:42)
"""
    frame = extract_stack_traces(text)[0].frames[0]
    assert frame.is_application_frame is True


def test_framework_frames_are_not_application_frames():
    text = """java.lang.NullPointerException: boom
\tat org.springframework.web.method.support.InvocableHandlerMethod.invoke(InvocableHandlerMethod.java:205)
\tat org.apache.catalina.core.ApplicationFilterChain.doFilter(ApplicationFilterChain.java:189)
\tat java.base/java.lang.reflect.Method.invoke(Method.java:568)
\tat net.sf.cglib.proxy.MethodProxy.invoke(MethodProxy.java:218)
"""
    frames = extract_stack_traces(text)[0].frames
    assert all(f.is_application_frame is False for f in frames)


# ---------------------------------------------------------------------------
# is_likely_root_cause
# ---------------------------------------------------------------------------

def test_single_exception_no_chain_is_its_own_root_cause():
    text = """java.lang.NullPointerException: boom
\tat com.x.A.a(A.java:1)
"""
    block = extract_stack_traces(text)[0]
    assert block.is_likely_root_cause is True


def test_deepest_caused_by_is_flagged_not_the_outer_wrapper():
    text = """java.lang.RuntimeException: outer failure
\tat com.x.A.a(A.java:1)
Caused by: java.sql.SQLException: connection refused
\tat com.x.B.b(B.java:2)
"""
    outer, inner = extract_stack_traces(text)
    assert outer.is_likely_root_cause is False
    assert inner.is_likely_root_cause is True


def test_suppressed_exception_never_flagged_as_root_cause():
    text = """java.lang.Exception: primary
\tat com.x.A.a(A.java:1)
\tSuppressed: java.io.IOException: close failed
\t\tat com.x.B.close(B.java:9)
"""
    primary, suppressed = extract_stack_traces(text)
    assert suppressed.is_likely_root_cause is False
    assert primary.is_likely_root_cause is True


def test_multiple_independent_incidents_each_get_their_own_root_cause():
    text = """java.lang.IllegalStateException: first incident
\tat com.x.A.a(A.java:1)
java.lang.RuntimeException: second incident outer
\tat com.x.B.b(B.java:2)
Caused by: java.sql.SQLException: second incident cause
\tat com.x.C.c(C.java:3)
"""
    blocks = extract_stack_traces(text)
    assert len(blocks) == 3
    first, second_outer, second_cause = blocks
    assert first.is_likely_root_cause is True
    assert second_outer.is_likely_root_cause is False
    assert second_cause.is_likely_root_cause is True

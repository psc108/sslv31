"""Scheduled job extraction (@Scheduled / @Schedules)."""
from app.services.jar_analyser.classfile import ClassInfo, MethodInfo, AnnotationInfo, AnnotationElement
from app.services.jar_analyser.scheduled_jobs import extract_scheduled_jobs, SCHEDULED, SCHEDULES


def _class_with_method(method: MethodInfo, class_name: str = "com/x/JobRunner") -> ClassInfo:
    return ClassInfo(
        class_name=class_name, superclass=None, interfaces=[],
        annotations=[], methods=[method], fields=[], class_file_version=61,
    )


def test_cron_schedule_extracted():
    ann = AnnotationInfo(descriptor=SCHEDULED, elements=[AnnotationElement("cron", "0 0 2 * * *")])
    method = MethodInfo(name="nightlyCleanup", descriptor="()V", annotations=[ann])
    jobs = extract_scheduled_jobs([_class_with_method(method)])
    assert len(jobs) == 1
    assert jobs[0].cron == "0 0 2 * * *"
    assert jobs[0].display == "cron: 0 0 2 * * *"
    assert jobs[0].is_config_driven is False


def test_fixed_rate_schedule_extracted():
    ann = AnnotationInfo(descriptor=SCHEDULED, elements=[AnnotationElement("fixedRate", 5000)])
    method = MethodInfo(name="poll", descriptor="()V", annotations=[ann])
    jobs = extract_scheduled_jobs([_class_with_method(method)])
    assert jobs[0].fixed_rate_ms == 5000
    assert "5000ms" in jobs[0].display
    assert "fixed rate" in jobs[0].display


def test_fixed_delay_schedule_extracted():
    ann = AnnotationInfo(descriptor=SCHEDULED, elements=[AnnotationElement("fixedDelay", 30000)])
    method = MethodInfo(name="reconcile", descriptor="()V", annotations=[ann])
    jobs = extract_scheduled_jobs([_class_with_method(method)])
    assert jobs[0].fixed_delay_ms == 30000
    assert "fixed delay" in jobs[0].display


def test_config_driven_cron_is_flagged_not_resolved():
    ann = AnnotationInfo(descriptor=SCHEDULED, elements=[AnnotationElement("cron", "${job.cron.expr}")])
    method = MethodInfo(name="job", descriptor="()V", annotations=[ann])
    jobs = extract_scheduled_jobs([_class_with_method(method)])
    assert jobs[0].is_config_driven is True
    assert jobs[0].cron == "${job.cron.expr}"


def test_fixed_rate_string_placeholder_is_config_driven():
    ann = AnnotationInfo(descriptor=SCHEDULED, elements=[AnnotationElement("fixedRateString", "${my.rate:60000}")])
    method = MethodInfo(name="job", descriptor="()V", annotations=[ann])
    jobs = extract_scheduled_jobs([_class_with_method(method)])
    assert jobs[0].is_config_driven is True
    assert "config-driven" in jobs[0].display


def test_zone_included_in_cron_display():
    ann = AnnotationInfo(descriptor=SCHEDULED, elements=[
        AnnotationElement("cron", "0 0 2 * * *"), AnnotationElement("zone", "UTC"),
    ])
    method = MethodInfo(name="job", descriptor="()V", annotations=[ann])
    jobs = extract_scheduled_jobs([_class_with_method(method)])
    assert jobs[0].zone == "UTC"
    assert "(UTC)" in jobs[0].display


def test_schedules_container_extracts_multiple():
    inner1 = AnnotationInfo(descriptor=SCHEDULED, elements=[AnnotationElement("cron", "0 0 2 * * *")])
    inner2 = AnnotationInfo(descriptor=SCHEDULED, elements=[AnnotationElement("cron", "0 0 14 * * *")])
    container = AnnotationInfo(descriptor=SCHEDULES, elements=[AnnotationElement("value", [inner1, inner2])])
    method = MethodInfo(name="twiceDaily", descriptor="()V", annotations=[container])
    jobs = extract_scheduled_jobs([_class_with_method(method)])
    assert len(jobs) == 2
    assert {j.cron for j in jobs} == {"0 0 2 * * *", "0 0 14 * * *"}


def test_no_scheduled_annotation_yields_nothing():
    method = MethodInfo(name="regularMethod", descriptor="()V", annotations=[])
    jobs = extract_scheduled_jobs([_class_with_method(method)])
    assert jobs == []


def test_declaring_class_captured():
    ann = AnnotationInfo(descriptor=SCHEDULED, elements=[AnnotationElement("fixedRate", 1000)])
    method = MethodInfo(name="tick", descriptor="()V", annotations=[ann])
    jobs = extract_scheduled_jobs([_class_with_method(method, "com/dxc/ecs/blobstore/CleanupJob")])
    assert jobs[0].declaring_class == "com.dxc.ecs.blobstore.CleanupJob"
    assert jobs[0].declaring_class_simple == "CleanupJob"

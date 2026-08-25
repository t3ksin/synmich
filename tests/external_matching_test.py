from synmich.core.migrator import _iso_to_epoch, match_existing_asset


def test_prefers_single_external_asset_over_upload_copies_with_shifted_video_time():
    filename = "2025-09-15_12-46-22_GX010229.MP4"
    candidates = [
        (
            "5fd7af69-d7b8-4997-bb8b-94003df0a541",
            "2025-09-15T12:45:46+00:00",
            None,
        ),
        (
            "7d10c5b6-884a-43c4-816f-2efc2ad9df94",
            "2025-09-15T12:45:46+00:00",
            None,
        ),
        (
            "7034ccbd-7fd8-46a8-9ecf-3c81007d9139",
            "2025-09-15T09:45:46+00:00",
            "1bb4e262-396e-4596-b051-c71e845aff33",
        ),
    ]

    assert (
        match_existing_asset(
            {filename.lower(): candidates},
            filename,
            _iso_to_epoch("2025-09-15T12:45:46+00:00"),
        )
        == "7034ccbd-7fd8-46a8-9ecf-3c81007d9139"
    )


def test_multiple_external_assets_still_require_capture_date_match():
    filename = "GOPR0023.JPG"
    candidates = [
        ("external-old", "2025-09-15T12:45:46+00:00", "library-a"),
        ("external-new", "2025-10-20T08:30:00+00:00", "library-a"),
    ]

    assert (
        match_existing_asset(
            {filename.lower(): candidates},
            filename,
            _iso_to_epoch("2025-10-20T08:30:30+00:00"),
        )
        == "external-new"
    )


def test_prefers_owner_path_when_multiple_external_assets_have_same_date():
    filename = "2025-03-04_15-02-23_IMG_2146.HEIC"
    candidates = [
        (
            "shared-copy",
            "2025-03-04T14:02:23.486+00:00",
            "shared-library",
            "/volume1/photo/2025-misc/2025-03-04_15-02-23_IMG_2146.HEIC",
        ),
        (
            "nino-copy",
            "2025-03-04T14:02:23.486+00:00",
            "nino-library",
            "/volume1/homes/Nino/Photos/PhotoSync/2025/03/"
            "2025-03-04_15-02-23_IMG_2146.HEIC",
        ),
        (
            "uploaded-copy",
            "2025-03-04T14:02:23.486+00:00",
            None,
            "/data/upload/c0e83c7c/photo.HEIC",
        ),
    ]

    assert (
        match_existing_asset(
            {filename.lower(): candidates},
            filename,
            _iso_to_epoch("2025-03-04T14:02:23.486+00:00"),
            owner_name="Nino",
        )
        == "nino-copy"
    )

"""The store is Cloudflare R2, and nothing about reaching it is AWS.

boto3 is still the client — R2 serves the S3 API and SigV4 is the only way in —
but that is an implementation detail of one function. The endpoint, the two
credentials and the region are R2's, read under R2's names, and a deployment
that half-configures them is told which half.

The region is not a variable at all. R2 signs everything `auto` and no other
value works, so a setting here could only ever be set wrong.
"""

from __future__ import annotations

import pytest

from interviewer.embeddings.artifacts import R2_REGION, _client, endpoint_url
from interviewer.embeddings.errors import EmbeddingUnavailable

R2 = "https://acc0unt.r2.cloudflarestorage.com"
CREDS = {"R2_ACCESS_KEY_ID": "token-id", "R2_SECRET_ACCESS_KEY": "token-secret"}


def test_the_endpoint_is_what_makes_it_r2():
    assert endpoint_url({"R2_ENDPOINT_URL": R2}) == R2
    client = _client({"R2_ENDPOINT_URL": R2, **CREDS})
    assert client.meta.endpoint_url == R2


def test_the_region_is_a_constant_rather_than_a_setting():
    assert R2_REGION == "auto"
    assert _client({"R2_ENDPOINT_URL": R2, **CREDS}).meta.region_name == "auto"


def test_a_bucket_with_no_endpoint_is_refused_rather_than_pointed_at_aws():
    with pytest.raises(EmbeddingUnavailable) as exc:
        _client({**CREDS})
    assert "R2_ENDPOINT_URL" in str(exc.value)


def test_missing_credentials_are_named_here_rather_than_inside_an_upload():
    with pytest.raises(EmbeddingUnavailable) as exc:
        _client({"R2_ENDPOINT_URL": R2})
    assert "R2_ACCESS_KEY_ID" in str(exc.value)
    assert "R2_SECRET_ACCESS_KEY" in str(exc.value)

    with pytest.raises(EmbeddingUnavailable):
        _client({"R2_ENDPOINT_URL": R2, "R2_ACCESS_KEY_ID": "token-id"})


def test_the_ambient_aws_environment_is_not_a_credential_source():
    """A host with AWS keys lying around does not quietly become the store."""
    with pytest.raises(EmbeddingUnavailable):
        _client({
            "R2_ENDPOINT_URL": R2,
            "AWS_ACCESS_KEY_ID": "ambient",
            "AWS_SECRET_ACCESS_KEY": "ambient",
        })


def test_the_credentials_used_are_the_r2_ones():
    creds = _client({"R2_ENDPOINT_URL": R2, **CREDS})._request_signer._credentials
    assert creds.access_key == "token-id"
    assert creds.secret_key == "token-secret"


def test_an_empty_value_is_not_a_value():
    assert endpoint_url({"R2_ENDPOINT_URL": "   "}) is None
    with pytest.raises(EmbeddingUnavailable):
        _client({"R2_ENDPOINT_URL": R2, "R2_ACCESS_KEY_ID": " ", **{"R2_SECRET_ACCESS_KEY": "s"}})


def test_an_upload_carries_no_checksum_trailer():
    """`when_supported` is boto3's default since 1.36 and is `aws-chunked` on
    the wire — the one thing a store serving the S3 API is least likely to
    agree with S3 about."""
    client = _client({"R2_ENDPOINT_URL": R2, **CREDS})
    assert client.meta.config.request_checksum_calculation == "when_required"

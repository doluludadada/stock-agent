"""Every settings value lives in one place: a code default, or config/appsetting.yaml."""

import pytest
import settings_defaults
from pydantic import ValidationError
from support.settings import APPSETTING, load_yaml

from b_application.config.app_config import AppConfig
from b_application.config.collect_config import StockBriefConfig, WorldBriefConfig


def test_no_setting_of_the_shipped_file_has_a_code_default() -> None:
    duplicated = settings_defaults.duplicated_settings(AppConfig, load_yaml(APPSETTING))

    assert [str(setting) for setting in duplicated] == []


@pytest.mark.parametrize("section", [StockBriefConfig, WorldBriefConfig])
def test_a_briefs_setting_cannot_be_a_value_its_rule_refuses(section: type[StockBriefConfig] | type[WorldBriefConfig]) -> None:
    """A setting its rule would refuse stopped every Pipeline from being built, not the settings from loading."""
    with pytest.raises(ValidationError):
        section(article_text_length=0)

    assert section(article_text_length=1).context_rule().article_text_length == 1

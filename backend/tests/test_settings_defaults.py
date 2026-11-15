"""A settings field that keeps a code default beside its config/appsetting.yaml value never disagrees with the YAML."""

import pytest
import settings_defaults
from pydantic import ValidationError
from support.settings import APPSETTING

from b_application.config.app_config import AppConfig
from b_application.config.collect_config import StockBriefConfig, WorldBriefConfig
from b_application.config.settings_loader import load_yaml


def test_no_code_default_disagrees_with_the_shipped_settings() -> None:
    duplicated = settings_defaults.duplicated_settings(AppConfig, load_yaml(APPSETTING))

    assert [str(setting) for setting in duplicated if setting.differs] == []


@pytest.mark.parametrize("section", [StockBriefConfig, WorldBriefConfig])
def test_a_briefs_setting_cannot_be_a_value_its_rule_refuses(section: type[StockBriefConfig] | type[WorldBriefConfig]) -> None:
    """A setting its rule would refuse stopped every Pipeline from being built, not the settings from loading."""
    with pytest.raises(ValidationError):
        section(article_text_length=0)

    assert section(article_text_length=1).context_rule().article_text_length == 1

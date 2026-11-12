"""The rules that decide which Path of Building configuration options a build has evidence for
(src/tools/build_tools.py _line_options). The sentences are the game's own wording, from poe2db."""
import pytest

from src.tools.build_tools import _blocked_options, _gem_lines, _line_options


@pytest.mark.parametrize("line, option", [
    ("If the target is Shocked , Consume their Shock to release a Lightning shockwave around the target and grant you "
     "a Power Charge .", "usePowerCharges"),
    ("15% chance to gain a Power Charge on Critical Hit", "usePowerCharges"),
    ("Gain a Frenzy Charge when you Freeze , Electrocute or Pin an enemy, no more than once every 8 seconds",
     "useFrenzyCharges"),
    ("40 % chance to gain an Endurance Charge when Supported Skills Fully Break Armour", "useEnduranceCharges"),
    ("5% chance to Blind Enemies on Hit", "conditionEnemyBlinded"),
    ("100% chance to Daze Enemies whose Hits you Block", "conditionEnemyDazed"),
    ("Always Poisons on Hit", "conditionEnemyPoisoned"),
    ("Minions from Supported Skills Blind Enemies within a 2 metre radius", "conditionEnemyBlinded"),
    ("Perform a circular slash that kicks up a Whirlwind around you, Slowing enemies and Blinding them", "conditionEnemyBlinded"),
    ("Supported Skills Daze when Hitting enemies that are on full life", "conditionEnemyDazed"),
    ("Does not Hit , but Poisons enemies as though Hitting them", "conditionEnemyPoisoned"),
    ("Consume charges from your Mana Flask to throw a flask that explodes, with a high chance to Shock .",
     "conditionEnemyShocked"),
    ("Shocks Enemies as though dealing 50 % more Damage", "conditionEnemyShocked"),
    ("Volatile Dead | Ignites enemies within 1.5 metre radius".split(" | ")[1], "conditionEnemyIgnited"),
    ("Chills Enemies as though dealing 300 % more damage", "conditionEnemyChilled"),
    ("Supported Skills have 10 % chance to Freeze", "conditionEnemyFrozen"),
    ("5% chance to inflict Bleeding on Hit", "conditionEnemyBleeding"),
    ("Supported Skills have 40 % chance to Poison on Hit", "conditionEnemyPoisoned"),
    ("Supported Skills Blind Enemies on Hit", "conditionEnemyBlinded"),
    ("10% chance to Daze on Hit", "conditionEnemyDazed"),
    ("8% increased Cast Speed if you've dealt a Critical Hit Recently", "conditionCritRecently"),
])
def test_a_line_that_gains_or_inflicts_is_evidence(line, option):
    assert option in _line_options(line, set())


@pytest.mark.parametrize("line, option", [
    ("Consume all Power Charges to charge your Quarterstaff with electricity", "usePowerCharges"),
    ("Buff grants 1 to 2 Added Quarterstaff Attack Lightning damage per Power Charge Consumed, up to your maximum "
     "Power Charges", "usePowerCharges"),
    ("+2 to Maximum Power Charges", "usePowerCharges"),
    ("25% chance when you gain a Power Charge to gain an additional Power Charge", "usePowerCharges"),
    ("Gain Endurance Charges instead of Power Charges", "usePowerCharges"),
    ("Gain Endurance Charges instead of Power Charges", "useEnduranceCharges"),
    ("2% chance that if you would gain Frenzy Charges, you instead gain up to your maximum number of Frenzy Charges",
     "useFrenzyCharges"),
    ("Gain 2% of Damage as Extra Fire Damage per Endurance Charge consumed Recently", "useEnduranceCharges"),
    ("Drenched enemies have 50 % more chance to be Shocked", "conditionEnemyShocked"),
    ("100 % more chance to Shock", "conditionEnemyShocked"),                  # changes a chance; the element decides
    ("15% increased chance to Shock", "conditionEnemyShocked"),
    ("Supported Skills have 30 % less chance to Shock", "conditionEnemyShocked"),
    ("10% chance to Aggravate Bleeding on targets you Hit", "conditionEnemyBleeding"),
    ("100% increased chance to inflict Bleeding against Enemies on full Life", "conditionEnemyBleeding"),
    ("10% increased chance to inflict Shock", "conditionEnemyShocked"),
    ("50% chance to Knock Back Bleeding Enemies with Hits", "conditionEnemyBleeding"),
    ("Bleeding Enemies you Kill Explode", "conditionEnemyBleeding"),
    ("Chill Enemies you Kill", "conditionEnemyChilled"),
    ("Enemies you inflict Bleeding on have 15% increased Attack Speed", "conditionEnemyBleeding"),
    ("Shocks caused by Supported Skills are reflected back to you", "conditionEnemyShocked"),
    ("Supports any skill that Hits enemies, causing inflicted Ignites to deal more damage but its Hits to deal less "
     "damage.", "conditionEnemyIgnited"),
    ("Supported Skills have 20 % chance to refresh Ignite duration on Critical Hit", "conditionEnemyIgnited"),
    ("Chill and Freeze on enemies in front of you are Consumed to fuel the Icestorm", "conditionEnemyChilled"),
    ("Supports any skill that Hits enemies, causing Freeze it inflicts to last longer.", "conditionEnemyFrozen"),
    ("Supports Persistent Buff Skills, causing Freeze applied to you to last for a shorter duration",
     "conditionEnemyFrozen"),
    ("Build Glory by inflicting Freeze , Shock or Ignite on enemies.", "conditionEnemyFrozen"),
    ("Poison inflicted with Supported Skills deals Damage faster the higher your Rage .", "conditionEnemyPoisoned"),
    ("Blind inflicted with Supported Skills has 20 % increased Effect", "conditionEnemyBlinded"),
    ("Supported Attacks cannot cause Bleeding", "conditionEnemyBleeding"),
    ("40% increased Damage against Bleeding Enemies", "conditionEnemyBleeding"),
    ("20% increased Critical Damage Bonus if you haven't dealt a Critical Hit Recently", "conditionCritRecently"),
    ("Chance to inflict Bleeding with Supported Skills is calculated from their base chance to Poison instead",
     "conditionEnemyBleeding"),
])
def test_a_line_that_only_uses_or_benefits_is_not(line, option):
    assert option not in _line_options(line, set())


def test_exposure_takes_its_element_from_the_text_or_the_gem():
    assert _line_options("Supported Skills inflict Exposure for 8 seconds on Shocking a target", {"lightning"}) == [
        "conditionEnemyLightningExposure"]
    assert _line_options("10% chance to inflict Cold Exposure on Hit", set()) == ["conditionEnemyColdExposure"]
    assert sorted(_line_options("Inflict Elemental Exposure on Hit, lowering Total Elemental Resistances by 50 %",
                                set())) == ["conditionEnemyColdExposure", "conditionEnemyFireExposure",
                                            "conditionEnemyLightningExposure"]
    assert _line_options("Supported Skills inflict Exposure", set()) == []          # no element known


@pytest.mark.parametrize("line, blocked", [
    ("Supported Skills Cannot inflict Shock", {"conditionEnemyShocked"}),
    ("Cannot inflict Freeze, Shock or Ignite", {"conditionEnemyFrozen", "conditionEnemyShocked", "conditionEnemyIgnited"}),
    ("Supported Skills cannot generate Frenzy Charges", {"useFrenzyCharges"}),
    ("Inflicts Bleeding on Hit", set()),
    ("Cannot Support Skills which consume Endurance Charges .", set()),
    ("Cannot support skills that Consume Freeze or Ignite .", set()),
    ("Secondary explosions cannot Consume Freeze", set()),
])
def test_cannot_lines_block_options_for_their_group(line, blocked):
    assert _blocked_options(line) == blocked


def test_gem_lines_include_the_level_table_effect_columns():
    record = {"description": "First. Second line", "extra_properties": ["Grants a thing"], "main_stat": None,
              "level_effects": [{"Level": "1", "Requires Level": "0", "Dex": "4",
                                 "Gain a Frenzy Charge when you Freeze an enemy": "x"}]}
    assert _gem_lines(record) == ["First.", "Second line", "Grants a thing",
                                  "Gain a Frenzy Charge when you Freeze an enemy"]

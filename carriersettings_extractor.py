#!/usr/bin/env python3

from collections import OrderedDict
from glob import glob
from itertools import product
import os.path
import sys
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from carrier_settings_pb2 import CarrierSettings, MultiCarrierSettings
from carrier_list_pb2 import CarrierList
from carrierId_pb2 import CarrierList as CarrierIdList

pb_path = sys.argv[1]

android_build_top = sys.argv[2]

apn_out = sys.argv[3]

cc_out = sys.argv[4]

device = sys.argv[5]

android_path_to_carrierid = (
    "packages/providers/TelephonyProvider/assets/latest_carrier_id"
)
carrier_id_list = CarrierIdList()
carrier_attribute_map = {}
with open(
    os.path.join(android_build_top, android_path_to_carrierid, "carrier_list.pb"), "rb"
) as pb:
    carrier_id_list.ParseFromString(pb.read())
for carrier_id_obj in carrier_id_list.carrier_id:
    for carrier_attribute in carrier_id_obj.carrier_attribute:
        for carrier_attributes in product(
            *(
                (s.lower() for s in getattr(carrier_attribute, i) or [""])
                for i in [
                    "mccmnc_tuple",
                    "imsi_prefix_xpattern",
                    "spn",
                    "plmn",
                    "gid1",
                    "preferred_apn",
                    "iccid_prefix",
                    "privilege_access_rule",
                ]
            )
        ):
            carrier_attribute_map[carrier_attributes] = carrier_id_obj.canonical_id

carrier_list = CarrierList()
all_settings = {}
carrier_list.ParseFromString(
    open(os.path.join(pb_path, "carrier_list.pb"), "rb").read()
)
# Load generic settings first
multi_settings = MultiCarrierSettings()
multi_settings.ParseFromString(open(os.path.join(pb_path, "others.pb"), "rb").read())
for setting in multi_settings.setting:
    all_settings[setting.canonical_name] = setting
# Load carrier specific files last, to allow overriding generic settings
for filename in glob(os.path.join(pb_path, "*.pb")):
    with open(filename, "rb") as pb:
        if os.path.basename(filename) == "carrier_list.pb":
            # Handled above already
            continue
        elif os.path.basename(filename) == "others.pb":
            # Handled above already
            continue
        else:
            setting = CarrierSettings()
            setting.ParseFromString(pb.read())
            if setting.canonical_name in all_settings:
                print(
                    "Overriding generic settings for " + setting.canonical_name,
                    file=sys.stderr,
                )
            all_settings[setting.canonical_name] = setting


# Unfortunately, python processors like xml and lxml, as well as command-line
# utilities like tidy, do not support the exact style used by AOSP for
# apns-full-conf.xml:
#
#  * indent: 2 spaces
#  * attribute indent: 4 spaces
#  * blank lines between elements
#  * attributes after first indented on separate lines
#  * closing tags of multi-line elements on separate, unindented lines
#
# Therefore, we build the file without using an XML processor.


class ApnElement:
    def __init__(self, apn, carrier_id):
        self.apn = apn
        self.carrier_id = carrier_id
        self.attributes = OrderedDict()
        self.add_attributes()

    def add_attribute(self, key, field=None, value=None):
        if value is not None:
            self.attributes[key] = value
        else:
            if field is None:
                field = key
            if self.apn.HasField(field):
                enum_type = self.apn.DESCRIPTOR.fields_by_name[field].enum_type
                value = getattr(self.apn, field)
                if enum_type is None:
                    if isinstance(value, bool):
                        self.attributes[key] = str(value).lower()
                    else:
                        self.attributes[key] = str(value)
                else:
                    self.attributes[key] = enum_type.values_by_number[value].name

    def add_attributes(self):
        try:
            self.add_attribute(
                "carrier_id",
                value=str(
                    carrier_attribute_map[
                        (
                            self.carrier_id.mcc_mnc,
                            self.carrier_id.imsi,
                            self.carrier_id.spn.lower(),
                            "",
                            self.carrier_id.gid1.lower(),
                            "",
                            "",
                            "",
                        )
                    ]
                ),
            )
        except KeyError:
            pass
        self.add_attribute("mcc", value=self.carrier_id.mcc_mnc[:3])
        self.add_attribute("mnc", value=self.carrier_id.mcc_mnc[3:])
        self.add_attribute("apn", "value")
        self.add_attribute("proxy")
        self.add_attribute("port")
        self.add_attribute("mmsc")
        self.add_attribute("mmsproxy", "mmsc_proxy")
        self.add_attribute("mmsport", "mmsc_proxy_port")
        self.add_attribute("user")
        self.add_attribute("password")
        self.add_attribute("server")
        self.add_attribute("authtype")
        self.add_attribute(
            "type",
            value=",".join(
                apn.DESCRIPTOR.fields_by_name["type"].enum_type.values_by_number[i].name
                for i in self.apn.type
            ).lower(),
        )
        self.add_attribute("protocol")
        self.add_attribute("roaming_protocol")
        self.add_attribute("bearer_bitmask")
        self.add_attribute("profile_id")
        self.add_attribute("modem_cognitive")
        self.add_attribute("max_conns")
        self.add_attribute("wait_time")
        self.add_attribute("max_conns_time")
        self.add_attribute("mtu")
        mvno = self.carrier_id.WhichOneof("mvno_data")
        if mvno:
            self.add_attribute(
                "mvno_type",
                value="gid" if mvno.startswith("gid") else mvno,
            )
            self.add_attribute(
                "mvno_match_data",
                value=getattr(self.carrier_id, mvno),
            )
        self.add_attribute("apn_set_id")
        # No source for integer carrier_id?
        self.add_attribute("skip_464xlat")
        self.add_attribute("user_visible")
        self.add_attribute("user_editable")


def indent(elem, level=0):
    """Based on https://effbot.org/zone/element-lib.htm#prettyprint"""
    i = "\n" + level * "    "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "    "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


# Anything where the value is a package name
unwanted_configs = [
    "carrier_settings_activity_component_name_string",
    "carrier_setup_app_string",
    "config_ims_package_override_string",
    "enable_apps_string_array",
    "gps.nfw_proxy_apps",
    "ci_action_on_sys_update_bool",
    "ci_action_on_sys_update_extra_string",
    "ci_action_on_sys_update_extra_val_string",
    "ci_action_on_sys_update_intent_string",
    "allow_adding_apns_bool",
    "apn_expand_bool",
    "hide_ims_apn_bool",
    "hide_preset_apn_details_bool",
    "read_only_apn_fields_string_array",
    "read_only_apn_types_string_array",
    "show_apn_setting_cdma_bool",
    "carrier_provisioning_app_string",
    "hide_enable_2g_bool",
    "com.google.android.dialer.display_wifi_calling_button_bool",
    "config_ims_rcs_package_override_string",
    "editable_enhanced_4g_lte_bool",
    "hide_enhanced_4g_lte_bool",
    "vonr_setting_visibility_bool",
    "editable_wfc_mode_bool",
    "editable_wfc_roaming_mode_bool",
    "moto_WEA3_overshoot_allowed",
    "moto_additional_international_roaming_network_string_array",
    "moto_allow_hold_in_gsm_call",
    "moto_app_directed_sms_enabled",
    "moto_append_filler_digits_to_iccid",
    "moto_auto_answer",
    "moto_auto_resume_holding_call",
    "moto_auto_resume_holding_call",
    "moto_auto_retry_enabled",
    "moto_back_to_auto_network_selection_timer",
    "moto_call_end_tone_and_call_end_toast",
    "moto_carrier_airplane_mode_alert_bool",
    "moto_carrier_chatbot_supported_bool",
    "moto_carrier_chatbot_supported_bool",
    "moto_carrier_fdn_numbers_string_array",
    "moto_carrier_format_device_info",
    "moto_carrier_hide_meid",
    "moto_carrier_specific_rtt_req_bool",
    "moto_carrier_specific_vice_req_bool",
    "moto_carrier_specific_vt_req_bool",
    "moto_carrier_specific_wfc_req_bool",
    "moto_carrier_vonr_available_bool",
    "moto_cdma_dbm_thresholds_int_array",
    "moto_cdma_ecio_thresholds_int_array",
    "moto_check_camped_csg_bool",
    "moto_common_rtt_enabled_bool",
    "moto_convert_plus_for_ims_call_bool",
    "moto_custom_config_string",
    "moto_customized_vvm_in_dialer_bool",
    "moto_default_disable_initial_addressbook_scan_value_int",
    "moto_delete_WEA_database",
    "moto_disable_2g_bool",
    "moto_display_noservice_dataiwlan_wificallingdisable",
    "moto_dss_int",
    "moto_ecbm_supported_bool",
    "moto_enable_bcch_location_service",
    "moto_enable_broadcast_phone_state_change",
    "moto_enable_service_dialing_number",
    "moto_enable_ussd_alert",
    "moto_enriched_call_common_bool",
    "moto_eri_banner",
    "moto_evdo_dbm_thresholds_int_array",
    "moto_evdo_ecio_thresholds_int_array",
    "moto_evdo_snr_thresholds_int_array",
    "moto_hide_delete_action_for_non_user_deletable_apn",
    "moto_hide_roaming_option_on_settings",
    "moto_hide_smsc_edit_option_bool",
    "moto_hide_wfc_mode_summary",
    "moto_ignore_ir94videoauth_for_video_calls",
    "moto_ims_call_priority_over_ussd_bool",
    "moto_ims_callcomposer_default_usersetting_bool",
    "moto_ims_useragent_format_str",
    "moto_ir94videoauth_default_int",
    "moto_launch_browser_for_captiveportal_mobile_bool",
    "moto_lppe_available_bool",
    "moto_lte_rsrp_thresholds_per_band_string_array",
    "moto_lte_show_one_bar_atleast_bool",
    "moto_mms_gowith_ims_rat_bool",
    "moto_mt_sms_filter_list",
    "moto_mt_sms_filter_list",
    "moto_multi_device_support",
    "moto_need_delay_otasp",
    "moto_operator_name_replace_string_array",
    "moto_preferred_display_name",
    "moto_prefix_block",
    "moto_prefix_block_bool",
    "moto_prompt_call_ap_mode",
    "moto_redial_alternate_service_call_over_cs",
    "moto_rtt_while_roaming_supported_bool",
    "moto_should_restore_anonymous_bool",
    "moto_should_restore_unknown_participant_bool",
    "moto_show_5g_warning_on_volte_off_bool",
    "moto_show_brazil_settings",
    "moto_show_customized_wfc_disclaimer_dialog",
    "moto_show_customized_wfc_help_and_dialog_bool",
    "moto_show_unsecured_wifi_network_dialog",
    "moto_show_wfc_ussd_disclaimer_bool",
    "moto_signal_strength_hysteresis_db_int",
    "moto_signal_strength_max_level_int",
    "moto_sprint_hd_codec",
    "moto_ssrsrp_signal_strength_hysteresis_db_int",
    "moto_ssrsrp_signal_threshold_offset_frequency_range_high_int",
    "moto_ssrsrp_signal_threshold_offset_frequency_range_low_int",
    "moto_ssrsrp_signal_threshold_offset_frequency_range_mid_int",
    "moto_ssrsrp_signal_threshold_offset_frequency_range_mmwave_int",
    "moto_sssinr_signal_strength_hysteresis_db_int",
    "moto_stir_shaken_common_req_bool",
    "moto_tdscdma_rscp_thresholds_int_array",
    "moto_uce_messaging_feature_enabled_bool",
    "moto_uce_video_feature_enabled_bool",
    "moto_update_cb_with_password_over_ims",
    "moto_update_ims_useragent_bool",
    "moto_use_only_cdmadbm_for_cdma_signal_bar_bool",
    "moto_use_only_evdodbm_for_evdo_signal_bar_bool",
    "moto_use_restore_number_for_conference",
    "moto_vt_common_req_bool",
    "moto_vzw_voice_call_worldphone",
    "moto_vzw_volte_specific_req",
    "moto_vzw_wfc_enabled_bool",
    "moto_vzw_world_phone",
    "moto_wcdma_ecno_thresholds_int_array",
    "moto_wcdma_rssi_thresholds_int_array",
    "moto_wfc_spn",
    "mtk_emc_rtt_guard_timer_bool",
    "mtk_key_vt_downgrade_in_bad_bitrate",
    "mtk_mt_rtt_without_precondition_bool",
    "mtk_rtt_audio_indication_supported_bool",
    "mtk_rtt_video_switch_supported_bool",
    "carrier_moto_allow_calls_over_IMS_only_bool",
    "moto_carrier_default_vonr_bool",
    "moto_disable_5GSA_during_wfc_call",
    "moto_networkstate_pingpong_supported_bool",
    "moto_networkstate_service_support_bool",
    "moto_networkstate_pingpong_supported_bool ",
    "moto_networkstate_service_support_bool ",
    "moto_smart_5g_enabled_bool",
    "moto_smart_5g_supported_bool",
    "moto_support_data_stall_detect_bool",
    "moto_support_data_stall_detect_bool ",
    "moto_sync_nrband_list_bool",
    "moto_wifi_cellular_switch_enabled_bool",
    "moto_cs_call_barring_service_class_int",
    "moto_user_default_nr_mode",
    "moto_force_apn_mvno_type_priority_string",
    "moto_config_spn_display_rule_array",
    "call_redirection_service_component_name_string",
    "carrier_vvm_package_name_string",
    
]

unwanted_configs_tensor = ["smart_forwarding_config_component_name_string"]

qualcomm_pixels = [
    "crosshatch",
    "blueline",
    "sargo",
    "bonito",
    "barbet",
    "bramble",
    "redfin",
    "sunfish",
    "coral",
    "flame",
]


def gen_config_tree(parent, config):
    if config.key in unwanted_configs:
        return
    if (config.key in unwanted_configs_tensor) and (device not in qualcomm_pixels):
        return
    value_type = config.WhichOneof("value")
    match value_type:
        case "text_value":
            # we do not ship proprietary carrier apps, only write values where it uses
            # AOSP ImsServiceEntitlement. fixes broken wi-fi calling on some carriers
            # for sandboxed Google Play users
            if (config.key == "wfc_emergency_address_carrier_app_string") and (
                str(getattr(config, value_type))
                != "com.android.imsserviceentitlement/.WfcActivationActivity"
            ):
                return
            sub_element = ET.SubElement(parent, "string")
            sub_element.set("name", config.key)
            sub_element.text = getattr(config, value_type)
        case "int_value":
            sub_element = ET.SubElement(parent, "int")
            sub_element.set("name", config.key)
            sub_element.set("value", str(getattr(config, value_type)))
        case "long_value":
            sub_element = ET.SubElement(parent, "long")
            sub_element.set("name", config.key)
            sub_element.set("value", str(getattr(config, value_type)))
        case "bool_value":
            sub_element = ET.SubElement(parent, "boolean")
            sub_element.set("name", config.key)
            sub_element.set("value", str(getattr(config, value_type)).lower())
        case "text_array":
            items = getattr(config, value_type).item
            # we do not ship "com.google.android.carriersetup", remove it from
            # carrier_app_wake_signal_config
            if config.key == "carrier_app_wake_signal_config":
                items = [
                    item
                    for item in items
                    if ("com.google.android.carriersetup/" not in str(item) or "com.motorola" not in str(item))
                ]
                # if there's only 1 value defined ("com.google.android.carriersetup") in
                # the list, just return so we're not writing an array of 0 values
                if len(items) == 0:
                    return
            sub_element = ET.SubElement(parent, "string-array")
            sub_element.set("name", config.key)
            sub_element.set("num", str(len(items)))
            for value in items:
                ET.SubElement(sub_element, "item").set("value", value)
        case "int_array":
            items = getattr(config, value_type).item
            sub_element = ET.SubElement(parent, "int-array")
            sub_element.set("name", config.key)
            sub_element.set("num", str(len(items)))
            for value in items:
                ET.SubElement(sub_element, "item").set("value", str(value))
        case "bundle":
            sub_element = ET.SubElement(parent, "pbundle_as_map")
            sub_element.set("name", config.key)
            configs = getattr(config, value_type).config
            for sub_config in configs:
                gen_config_tree(sub_element, sub_config)
        case "double_value":
            raise TypeError(f"Found Config value type: {value_type}")
            sub_element = ET.SubElement(parent, "double")
            sub_element.set("name", config.key)
            sub_element.set("value", str(getattr(config, value_type)))
        case _:
            print(f"Unknown Config value type: {value_type}")
            return


carrier_config_root = ET.Element("carrier_config_list")

with open(apn_out, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n\n')
    f.write('<apns version="8">\n\n')

    for entry in carrier_list.entry:
        setting = all_settings[entry.canonical_name]
        for apn in setting.apns.apn:
            f.write("  <apn carrier={}\n".format(quoteattr(apn.name)))
            apn_element = ApnElement(apn, entry.carrier_id[0])
            for key, value in apn_element.attributes.items():
                # Absolutely horrendous fix to stop NumberFormatException
                value = value.replace("SKIP_464XLAT_DEFAULT", "-1")
                value = value.replace("SKIP_464XLAT_DISABLE", "0")
                value = value.replace("SKIP_464XLAT_ENABLE", "1")
                f.write("      {}={}\n".format(escape(key), quoteattr(value)))
            f.write("  />\n\n")

        carrier_config_element = ET.SubElement(
            carrier_config_root,
            "carrier_config",
        )
        carrier_config_element.set("mcc", entry.carrier_id[0].mcc_mnc[:3])
        carrier_config_element.set("mnc", entry.carrier_id[0].mcc_mnc[3:])
        for field in ["spn", "imsi", "gid1"]:
            if entry.carrier_id[0].HasField(field):
                carrier_config_element.set(
                    field,
                    getattr(entry.carrier_id[0], field),
                )

        for config in setting.configs.config:
            gen_config_tree(carrier_config_element, config)

    f.write("</apns>\n")

indent(carrier_config_root)
carrier_config_tree = ET.ElementTree(carrier_config_root)
root_carrier_config_tree = carrier_config_tree.getroot()

# dict containing lookups for each mccmnc combo representing each file,
# which contains a list of all configs which are dicts
carrier_config_mccmnc_aggregated = {}

for lone_carrier_config in root_carrier_config_tree:
    # append mnc to mcc to form identifier used to lookup carrier XML in CarrierConfig
    # app
    if (
        ("gid1" not in lone_carrier_config.attrib)
        and ("spn" not in lone_carrier_config.attrib)
        and ("imsi" not in lone_carrier_config.attrib)
    ):
        front = True
    else:
        front = False

    mccmnc_combo = (
        "carrier_config_mccmnc_"
        + lone_carrier_config.attrib["mcc"]
        + lone_carrier_config.attrib["mnc"]
        + ".xml"
    )

    # handle multiple carrier configurations under the same mcc and mnc combination
    if mccmnc_combo not in carrier_config_mccmnc_aggregated:
        blank_list = []
        carrier_config_mccmnc_aggregated[mccmnc_combo] = blank_list
    temp_list = carrier_config_mccmnc_aggregated[mccmnc_combo]
    if front is True:
        temp_list.insert(0, lone_carrier_config)
    else:
        temp_list.append(lone_carrier_config)
    carrier_config_mccmnc_aggregated[mccmnc_combo] = temp_list


with open(cc_out, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n')
    f.write("<carrier_config_list>\n")
    for configfile in carrier_config_mccmnc_aggregated:
        config_list = carrier_config_mccmnc_aggregated[configfile]
        for config in config_list:
            config_tree = ET.ElementTree(config)
            config_tree = config_tree.getroot()
            indent(config_tree)
            single_carrier_config = ET.tostring(config_tree, encoding="unicode")
            single_carrier_config = str(single_carrier_config)
            # workaround for converting wrongfully made no sim config to global defaults
            # for device config
            single_carrier_config = single_carrier_config.replace(
                ' mcc="000" mnc="000"', ""
            )
            f.write(single_carrier_config)
    f.write("</carrier_config_list>\n")
    f.close()

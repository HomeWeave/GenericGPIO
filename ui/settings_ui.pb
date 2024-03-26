root {
  scroll_layout {
    containers {
      id: "btnAddDevices"
      button {
        text: "Add Device"
        on_click {
          actions {
            action_id: "show_container"
            additional_context {
              key: "replacementTarget"
              value: "addDeviceContainer"
            }
          }
        }
      }
    }
    containers {
      id: "addDeviceContainer"
      replacement_target: "addDeviceContainer"
      options {
        hide: true
      }
      grid_layout {
        containers {
          id: "dropDownDeviceTypes"
          drop_down {
            items {
              item_id: "SimpleSensorDevice"
              item_text: "Simple Sensor Device"
            }
            items {
              item_id: "SimpleActuatorDevice"
              item_text: "Simple Actuator Device"
            }
            items {
              item_id: "MotionSensorDevice"
              item_text: "Motion Sensor Device"
            }
          }
        }
        containers {
          id: "btnAddDeviceSubmit"
          button {
            text: "Add"
            on_click {
              actions {
                action_id: "add_device"
              }
            }
          }
        }
      }
    }
    containers {
      id: "txtLoadingDevices"
      text {
        text: "Loading devices.."
      }
      replacement_target: "devices_section"
    }
  }
}
onload_actions_list {
  actions {
    action_id: "get_all_settings"
  }
}
subscription_info {
  subscriptions {
    index: 1
    actions_list {
      actions {
        action_id: "handle_settings_change"
      }
    }
  }
  subscription_index_action {
    actions {
      jq_action {
        transform_expression: "1"
      }
      conditional {
        jq_conditional: ".[\"$result\"].type == \"settings\""
      }
    }
  }
  preprocess {
    actions {
      parse_action {
        string_to_json: true
      }
    }
  }
}
configured_actions {
  key: "send_data"
  value {
    actions {
      apply_template_to_context_action {
        template: "{{ payload }}"
        target_id: "JsonStr"
      }
    }
    actions {
      parse_action {
        context_id: "JsonStr"
        target_id: "Json"
        string_to_json: true
      }
    }
    actions {
      serialize_action {
        context_id: "Json"
        target_id: "JsonSerialized"
        json: true
      }
    }
    actions {
      server_action {
        channel_index: 1
        context_id: "JsonSerialized"
      }
    }
  }
}
configured_actions {
  key: "get_all_settings"
  value {
    actions {
      action_id: "send_data"
      additional_context {
        key: "payload"
        value: "{ 'action': 'get_all_settings' }"
      }
    }
  }
}
configured_actions {
  key: "add_device"
  value {
    actions {
      input_control_action {
        bus_key: "dropDownDeviceTypes"
        retrieve_value: true
        target_id: "new_device_type"
      }
    }
    actions {
      action_id: "send_data"
      additional_context {
        key: "payload"
        value: "{ 'action': 'add_device', 'type': '{{ new_device_type }}' }"
      }
    }
  }
}
configured_actions {
  key: "handle_settings_change"
  value {
    actions {
      jq_action {
        transform_expression: ".payload"
      }
    }
    actions {
      store_to_global_context_action {
        target_id: "latest_settings"
      }
    }
    actions {
      apply_template_to_context_action {
        target_id: "devices_ui_pb"
        template: {{{ LOAD_MULTILINE_ESCAPED_STR: ui/settings_devices_ui.jsontemplate }}}
      }
    }
    actions {
      parse_action {
        string_to_json: true
      }
    }
    actions {
      parse_action {
        parse_json_proto_type: "anton.ui.Container"
      }
    }
    actions {
      container_action {
        bus_key: "devices_section"
      }
    }
  }
}
configured_actions {
  key: "update_container"
  value {
    actions {
      apply_template_to_context_action {
        template: "{{ payload }}"
      }
    }
    actions {
      parse_action {
        string_to_json: true
      }
    }
    actions {
      parse_action {
        parse_json_proto_type: "anton.ui.Container"
      }
    }
    actions {
      container_action {
        bus_key: "{{replacementTarget}}"
        operation_type: kContainerMerge
      }
    }
  }
}
configured_actions {
  key: "hide_container"
  value {
    actions {
      action_id: "update_container"
      additional_context {
        key: "payload"
        value: "{'options': {'hide': true }}"
      }
    }
  }
}
configured_actions {
  key: "show_container"
  value {
    actions {
      action_id: "update_container"
      additional_context {
        key: "payload"
        value: "{'options': {'hide': false }}"
      }
    }
  }
}

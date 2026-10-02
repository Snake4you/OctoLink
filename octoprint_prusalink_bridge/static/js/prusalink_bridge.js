$(function() {
    function PrusaLinkBridgeViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0];

        // Connection test state
        self.testingConnection = ko.observable(false);
        self.connectionTestMessage = ko.observable("");
        self.connectionTestClass = ko.observable("");

        // Telemetry Observables
        self.isOnline = ko.observable(false);
        self.state = ko.observable("OFFLINE");
        self.nozzleActual = ko.observable(null);
        self.nozzleTarget = ko.observable(null);
        self.bedActual = ko.observable(null);
        self.bedTarget = ko.observable(null);
        self.axisX = ko.observable(null);
        self.axisY = ko.observable(null);
        self.axisZ = ko.observable(null);
        self.speed = ko.observable(null);
        self.flow = ko.observable(null);
        self.fanHotend = ko.observable(null);
        self.fanPrint = ko.observable(null);
        self.jobFile = ko.observable(null);
        self.progress = ko.observable(null);
        self.timePrinting = ko.observable(null);
        self.timeRemaining = ko.observable(null);
        self.prusaIp = ko.observable("");
        self.printerName = ko.observable("Prusa MK3.5S");

        // Thumbnail & Filament Observables
        self.thumbnailUrl = ko.observable(null);
        self.thumbnailPath = ko.observable(null);
        self.filamentType = ko.observable(null);
        self.filamentWeightG = ko.observable(null);
        self.filamentLengthM = ko.observable(null);
        self.filamentVolumeCm3 = ko.observable(null);
        self.filamentCost = ko.observable(null);
        self.firstLayerInspecting = ko.observable(false);

        self.onBeforeBinding = function () {
            if (self.settingsViewModel && self.settingsViewModel.settings) {
                self.settings = self.settingsViewModel.settings;
            }
        };

        self.onSettingsShown = function () {
            if (self.settingsViewModel && self.settingsViewModel.settings) {
                self.settings = self.settingsViewModel.settings;
            }
        };

        if (self.settingsViewModel && self.settingsViewModel.settings) {
            self.settings = self.settingsViewModel.settings;
        }

        // Computed formatters
        self.stateClass = ko.pureComputed(function() {
            var st = (self.state() || "").toUpperCase();
            if (st === "PRINTING") return "label-info";
            if (st === "PAUSED") return "label-warning";
            if (st === "FINISHED" || st === "OPERATIONAL" || st === "READY") return "label-success";
            if (st === "ERROR" || st === "STOPPED") return "label-important";
            return "label-inverse";
        });

        self.formatZ = ko.pureComputed(function() {
            var z = self.axisZ();
            if (z === null || z === undefined) return "-";
            return parseFloat(z).toFixed(2) + " mm";
        });

        self.formatProgress = ko.pureComputed(function() {
            var p = self.progress();
            if (p === null || p === undefined) return "0%";
            return parseFloat(p).toFixed(1) + "%";
        });

        self.formatTime = function(seconds) {
            if (!seconds || seconds <= 0) return "--:--";
            var h = Math.floor(seconds / 3600);
            var m = Math.floor((seconds % 3600) / 60);
            var s = seconds % 60;
            if (h > 0) {
                return h + "h " + (m < 10 ? "0" : "") + m + "m";
            }
            return m + "m " + (s < 10 ? "0" : "") + s + "s";
        };

        self.formatRemaining = ko.pureComputed(function() {
            return self.formatTime(self.timeRemaining());
        });

        self.formatElapsed = ko.pureComputed(function() {
            return self.formatTime(self.timePrinting());
        });

        self.formatFilamentWeight = ko.pureComputed(function() {
            var w = self.filamentWeightG();
            if (w === null || w === undefined) return "-";
            return parseFloat(w).toFixed(1) + " g";
        });

        self.formatFilamentLength = ko.pureComputed(function() {
            var l = self.filamentLengthM();
            if (l === null || l === undefined) return "-";
            return parseFloat(l).toFixed(2) + " m";
        });

        self.formatFilamentVolume = ko.pureComputed(function() {
            var v = self.filamentVolumeCm3();
            if (v === null || v === undefined) return "-";
            return parseFloat(v).toFixed(1) + " cm³";
        });

        self.formatFilamentCost = ko.pureComputed(function() {
            var c = self.filamentCost();
            if (c === null || c === undefined) return null;
            return parseFloat(c).toFixed(2) + " €";
        });

        self.formatFilamentSummary = ko.pureComputed(function() {
            var parts = [];
            if (self.filamentWeightG() !== null && self.filamentWeightG() !== undefined) {
                parts.push(parseFloat(self.filamentWeightG()).toFixed(1) + " g");
            }
            if (self.filamentLengthM() !== null && self.filamentLengthM() !== undefined) {
                parts.push(parseFloat(self.filamentLengthM()).toFixed(2) + " m");
            }
            if (parts.length > 0) return parts.join(" / ");
            if (self.filamentType()) return self.filamentType();
            return "-";
        });

        self.hasFilamentInfo = ko.pureComputed(function() {
            return Boolean(self.filamentType() || self.filamentWeightG() !== null || self.filamentLengthM() !== null);
        });

        self.prusaLinkUrl = ko.pureComputed(function() {
            var ip = self.prusaIp();
            if (!ip && self.settings && self.settings.plugins && self.settings.plugins.prusalink_bridge) {
                ip = ko.unwrap(self.settings.plugins.prusalink_bridge.prusa_ip) || "";
            }
            return ip ? ("http://" + ip) : "#";
        });

        // Data updating
        self.updateFromData = function(data) {
            if (!data) return;
            if (data.online !== undefined) self.isOnline(Boolean(data.online));
            if (data.state !== undefined) self.state(data.state || "OFFLINE");
            if (data.temp_nozzle !== undefined) self.nozzleActual(data.temp_nozzle);
            if (data.target_nozzle !== undefined) self.nozzleTarget(data.target_nozzle);
            if (data.temp_bed !== undefined) self.bedActual(data.temp_bed);
            if (data.target_bed !== undefined) self.bedTarget(data.target_bed);
            if (data.axis_x !== undefined) self.axisX(data.axis_x);
            if (data.axis_y !== undefined) self.axisY(data.axis_y);
            if (data.axis_z !== undefined) self.axisZ(data.axis_z);
            if (data.speed !== undefined) self.speed(data.speed);
            if (data.flow !== undefined) self.flow(data.flow);
            if (data.fan_hotend !== undefined) self.fanHotend(data.fan_hotend);
            if (data.fan_print !== undefined) self.fanPrint(data.fan_print);
            if (data.job_file !== undefined) self.jobFile(data.job_file);
            if (data.progress !== undefined) self.progress(data.progress);
            if (data.time_printing !== undefined) self.timePrinting(data.time_printing);
            if (data.time_remaining !== undefined) self.timeRemaining(data.time_remaining);
            if (data.prusa_ip) self.prusaIp(data.prusa_ip);
            if (data.printer_name) self.printerName(data.printer_name);
            if (data.thumbnail_url !== undefined) self.thumbnailUrl(data.thumbnail_url);
            if (data.thumbnail_path !== undefined) self.thumbnailPath(data.thumbnail_path);
            if (data.filament_type !== undefined) self.filamentType(data.filament_type);
            if (data.filament_weight_g !== undefined) self.filamentWeightG(data.filament_weight_g);
            if (data.filament_length_m !== undefined) self.filamentLengthM(data.filament_length_m);
            if (data.filament_volume_cm3 !== undefined) self.filamentVolumeCm3(data.filament_volume_cm3);
            if (data.filament_cost !== undefined) self.filamentCost(data.filament_cost);
            if (data.first_layer_inspecting !== undefined) self.firstLayerInspecting(Boolean(data.first_layer_inspecting));
        };

        self.onDataUpdaterPluginMessage = function(plugin, data) {
            if (plugin !== "prusalink_bridge") return;
            self.updateFromData(data);
        };

        self.requestData = function() {
            $.ajax({
                url: "/api/plugin/prusalink_bridge",
                type: "GET",
                dataType: "json",
                cache: false,
                success: function(response) {
                    self.updateFromData(response);
                }
            });
        };

        self.onStartup = function() {
            self.requestData();
            // Periodic fallback every 4s
            setInterval(self.requestData, 4000);
        };

        self.sendJobCommand = function(cmd) {
            OctoPrint.simpleApiCommand("prusalink_bridge", "send_command", {command: cmd})
                .done(function(resp) {
                    if (resp && resp.message) {
                        new PNotify({
                            title: "PrusaLink",
                            text: resp.message,
                            type: resp.success ? "success" : "notice"
                        });
                    }
                    setTimeout(self.requestData, 1000);
                });
        };

        self.testPrusaLinkConnection = function() {
            var ip = "";
            var apiKey = "";
            if (self.settings && self.settings.plugins && self.settings.plugins.prusalink_bridge) {
                ip = ko.unwrap(self.settings.plugins.prusalink_bridge.prusa_ip) || "";
                apiKey = ko.unwrap(self.settings.plugins.prusalink_bridge.prusa_api_key) || "";
            }

            if (!ip) {
                self.connectionTestMessage("Bitte zuerst eine IP-Adresse eintragen.");
                self.connectionTestClass("text-error");
                return;
            }

            self.testingConnection(true);
            self.connectionTestMessage("Prüfe Verbindung zu " + ip + "...");
            self.connectionTestClass("text-info");

            OctoPrint.simpleApiCommand("prusalink_bridge", "test_connection", {
                prusa_ip: ip,
                prusa_api_key: apiKey
            })
            .done(function(response) {
                if (response && response.success) {
                    self.connectionTestMessage(response.message || "Verbindung erfolgreich!");
                    self.connectionTestClass("text-success");
                    self.requestData();
                } else {
                    self.connectionTestMessage(response.message || "Verbindungsfehler aufgetreten.");
                    self.connectionTestClass("text-error");
                }
            })
            .fail(function(xhr) {
                var errMsg = "Fehler bei der Verbindung zu OctoPrint.";
                if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
                    errMsg = xhr.responseJSON.message;
                }
                self.connectionTestMessage(errMsg);
                self.connectionTestClass("text-error");
            })
            .always(function() {
                self.testingConnection(false);
            });
        };

        self.onAfterBinding = function() {
            self.injectIntoDashboardPlugin();
        };

        self.injectIntoDashboardPlugin = function() {
            var $dash = $("#tab_plugin_dashboard");
            if ($dash.length && $("#prusalink_dashboard_widget").length === 0) {
                var widgetHtml = '<div id="prusalink_dashboard_widget" class="dashboard-widget" style="margin-top:15px; padding:12px; background:#fafafa; border:1px solid #ddd; border-radius:4px;">' +
                    '<h5 style="margin-top:0; border-bottom:1px solid #eee; padding-bottom:5px;"><i class="fa fa-print icon-print"></i> PrusaLink Info <span class="label pull-right" data-bind="css: stateClass, text: state"></span></h5>' +
                    '<div class="row-fluid text-center">' +
                    '  <div class="span2" data-bind="visible: thumbnailUrl">' +
                    '    <img data-bind="attr: {src: thumbnailUrl}" style="max-height:55px; border-radius:3px;" />' +
                    '  </div>' +
                    '  <div class="span2"><strong>Z-Höhe:</strong><br><span data-bind="text: formatZ"></span></div>' +
                    '  <div class="span3"><strong>Filament:</strong><br><span class="badge" data-bind="visible: filamentType, text: filamentType"></span> <span data-bind="text: formatFilamentSummary"></span></div>' +
                    '  <div class="span2"><strong>Hotend-Fan:</strong><br><span data-bind="text: fanHotend() !== null ? (fanHotend() + \' RPM\') : \'-\'"></span></div>' +
                    '  <div class="span3"><strong>Speed / Flow:</strong><br><span data-bind="text: (speed() || 100) + \'% / \' + (flow() || 100) + \'%\'"></span></div>' +
                    '</div>' +
                    '</div>';

                var $target = $dash.find(".container-fluid, .dashboard-container").first();
                if ($target.length) {
                    $target.prepend(widgetHtml);
                } else {
                    $dash.prepend(widgetHtml);
                }
                var widgetEl = document.getElementById("prusalink_dashboard_widget");
                if (widgetEl) {
                    try {
                        ko.applyBindings(self, widgetEl);
                    } catch(e) {}
                }
            }
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: PrusaLinkBridgeViewModel,
        dependencies: ["settingsViewModel"],
        elements: [
            "#settings_plugin_prusalink_bridge",
            "#tab_plugin_prusalink_bridge",
            "#sidebar_plugin_prusalink_bridge"
        ]
    });
});

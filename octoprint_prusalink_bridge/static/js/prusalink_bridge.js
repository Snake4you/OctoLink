$(function() {
    function PrusaLinkBridgeViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0];

        self.testingConnection = ko.observable(false);
        self.connectionTestMessage = ko.observable("");
        self.connectionTestClass = ko.observable("");

        self.testPrusaLinkConnection = function() {
            var ip = self.settingsViewModel.settings.plugins.prusalink_bridge.prusa_ip();
            var apiKey = self.settingsViewModel.settings.plugins.prusalink_bridge.prusa_api_key();

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
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: PrusaLinkBridgeViewModel,
        dependencies: ["settingsViewModel"],
        elements: ["#settings_plugin_prusalink_bridge"]
    });
});

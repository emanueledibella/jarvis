import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import RemoteBootstrap from "./Remote";
import { getInterfaceLanguage, setInterfaceLanguage } from "./localization";
setInterfaceLanguage(getInterfaceLanguage());
import "./style.css";
import "./hud.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RemoteBootstrap><App /></RemoteBootstrap>
  </React.StrictMode>,
);

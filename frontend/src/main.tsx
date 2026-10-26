import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import VendorPortal from "./VendorPortal";
import "./styles.css";

const view = new URLSearchParams(window.location.search).get("view");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {view === "vendor" ? <VendorPortal /> : <App />}
  </React.StrictMode>,
);


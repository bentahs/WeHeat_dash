import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
from pymodbus.client import ModbusTcpClient

# IP-adressen van Belimo actuatoren
belimo_ips = ["192.168.0.11"]

# Registers en namen
register_names = {
    0: "Valve Position [%]",
    4: "Flow Setpoint [l/min]",
    5: "Power Setpoint [kW]",
    7: "Flow [m^3/h]",
    15: "Setpoint Absolute Volumetric Flow [m^3/h]",
    19: "Temperature 1 (remote) [°C]",
    21: "Temperature 2 (sensor) [°C]",
    23: "Delta T [°C]"
}
desired_registers = list(register_names.keys())

# Session state setup
if "running" not in st.session_state:
    st.session_state["running"] = False
if "data_log" not in st.session_state:
    st.session_state["data_log"] = pd.DataFrame(columns=["Tijd", "Actuator"] + list(register_names.values()))

def read_belimo_data(ip):
    client = ModbusTcpClient(ip)
    client.connect()
    try:
        result = client.read_holding_registers(address=0, count=124)
        if result.isError():
            return [], f"⚠️ Fout bij uitlezen van {ip}: {result}"
        return list(result.registers), None
    except Exception as e:
        return [], f"⚠️ Fout bij uitlezen van {ip}: {str(e)}"
    finally:
        client.close()

def write_belimo_data(ip, register, slider_value):
    value = int(slider_value * 100)
    client = ModbusTcpClient(ip)
    client.connect()
    try:
        result = client.write_register(register, value)
        if result.isError():
            return f"⚠️ Fout bij schrijven naar register {register} op {ip}: {result}"
        return f"✅ Succesvol geschreven naar {ip}: {value}"
    except Exception as e:
        return f"⚠️ Fout bij schrijven naar register {register} op {ip}: {str(e)}"
    finally:
        client.close()

def scale_value(register, value):
    if register in [7, 15]:
        return value * 36
    elif register in [4, 5, 19, 21, 23]:
        return value / 100.0
    else:
        return value

def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

def main():
    st.set_page_config(page_title="Belimo Live Control Dashboard", layout="wide")
    st.markdown("""
    <style>
    .block-container {
        padding-top: 1rem;
    }
    </style>
    """, unsafe_allow_html=True)
    st.title("Belimo Actuator Live Besturing")

    tab1, tab2, tab3 = st.tabs(["Klepbesturing", "Live Data Monitoren", "Data Analyse"])

    # --- TAB 1 ---
    with tab1:
        st.subheader("⚙️ Bestuur Kleppen")
        cols = st.columns(4)
        valve_positions = {}

        for i, ip in enumerate(belimo_ips):
            with cols[i]:
                valve_positions[ip] = st.slider(f"{ip} (%):", 0, 100, 0)
        
        if st.button("✅ Stuur waarden naar alle actuatoren"):
            for ip, valve_position in valve_positions.items():
                response = write_belimo_data(ip, 0, valve_position)
                st.success(f"{response} voor {ip}")

    # --- TAB 2 ---
    with tab2:
        st.subheader("📡 Live Monitoring & Alarmen")
        st.markdown("""
            <style>
            div[data-baseweb="select"] {
                font-size: 14px;
                min-height: 35px;
            }

            div[data-baseweb="select"] > div {
                width: 300px !important;
            }
            </style>
        """, unsafe_allow_html=True)
        selected_actuators = st.multiselect("Selecteer actuatoren:", belimo_ips, default=[belimo_ips[0]])

        col1, col2, col3 = st.columns([1, 1, 8])
        with col1:
            if st.button("▶️ Start Monitoring", use_container_width=False):
                st.session_state["running"] = True
        with col2:
            if st.button("⏹️ Stop Monitoring", use_container_width=False):
                st.session_state["running"] = False


        # Alarminstellingen per actuator
        st.markdown("### 🔧 Alarmgrenzen")

        alarm_settings = {}

        for ip in selected_actuators:
            with st.expander(f"Alarminstellingen voor {ip}"):
                col1, col2, col3, col4, col5, col6, col7 = st.columns([2, 0.5, 2, 0.5, 2, 0.5, 4])
                with col1:
                    t1_min = st.slider(f"Minimale T Aanvoer [°C]", 5.0, 60.0, 20.0, 0.5, key=f"{ip}_t1_min")
                    t1_max = st.slider(f"Maximale T Aanvoer [°C]", 5.0, 60.0, 25.0, 0.5, key=f"{ip}_t1_max")
                with col3:
                    t2_min = st.slider(f"Minimale T Retour [°C]", 5.0, 60.0, 20.0, 0.5, key=f"{ip}_t2_min")
                    t2_max = st.slider(f"Maximale T Retour [°C]", 5.0, 60.0, 25.0, 0.5, key=f"{ip}_t2_max")
                with col5:
                    dt_min = st.slider(f"Minimale ΔT [°C]", 0.0, 5.0, 0.0, 0.1, key=f"{ip}_dt_min")
                    dt_max = st.slider(f"Maximale ΔT [°C]", 0.0, 5.0, 5.0, 0.1, key=f"{ip}_dt_max")
                with col7:
                    flow_min = st.slider(f"Minimale Flow [m^3/h]", 0, 2000, 1000, 10, key=f"{ip}_flow_min")
                    flow_max = st.slider(f"Maximale Flow [m^3/h]", 0, 2000, 1300, 10, key=f"{ip}_flow_max")
                alarm_settings[ip] = {
                    "t1_min": t1_min, "t1_max": t1_max,
                    "t2_min": t2_min, "t2_max": t2_max,
                    "dt_min": dt_min, "dt_max": dt_max,
                    "flow_min": flow_min, "flow_max": flow_max
                }
        col1, col2, col3 = st.columns(3)  # Zorg ervoor dat de grafieken in 3 kolommen komen.

        with col1:
            chart1 = st.empty()
        with col2:
            chart2 = st.empty()
        with col3:
            chart3 = st.empty()

        alarm_placeholder = st.empty()

        while st.session_state.get("running", False):
            for ip in selected_actuators:
                registers, error = read_belimo_data(ip)
                if error:
                    st.warning(error)
                    continue
                elif registers:
                    timestamp = time.strftime("%H:%M:%S")
                    reg_values = {register_names[reg]: scale_value(reg, registers[reg]) for reg in desired_registers}
                    reg_values["Tijd"] = timestamp
                    reg_values["Actuator"] = ip

                    st.session_state["data_log"] = pd.concat(
                        [st.session_state["data_log"], pd.DataFrame([reg_values])],
                        ignore_index=True
                    ).tail(1000000)

                    # Alarmcontrole
                    t1 = reg_values["Temperature 1 (remote) [°C]"]
                    t2 = reg_values["Temperature 2 (sensor) [°C]"]
                    dt = reg_values["Delta T [°C]"]
                    flow = reg_values["Flow [m^3/h]"]
                    settings = alarm_settings[ip]
                    alerts = []

                    if not (settings["t1_min"] <= t1 <= settings["t1_max"]):
                        alerts.append(f"❗ [{ip}] T1 buiten bereik: {t1:.2f} °C")
                    if not (settings["t2_min"] <= t2 <= settings["t2_max"]):
                        alerts.append(f"❗ [{ip}] T2 buiten bereik: {t2:.2f} °C")
                    if not (settings["dt_min"] <= dt <= settings["dt_max"]):
                        alerts.append(f"❗ [{ip}] ΔT buiten bereik: {dt:.2f} °C")
                    if not (settings["flow_min"] <= flow <= settings["flow_max"]):
                        alerts.append(f"❗ [{ip}] Flow buiten bereik: {flow:.2f} m^3/h")

                    with alarm_placeholder.container():
                        if alerts:
                            for a in alerts:
                                st.warning(a)
                        else:
                            st.success(f"✅ {ip}: Alle waardes binnen grenzen.")

            # Laatste 10s tonen
            df = st.session_state["data_log"]
            df["Tijd"] = pd.to_datetime(df["Tijd"])  # eerste stap: naar datetime
            recent = df[df["Tijd"] >= df["Tijd"].max() - pd.Timedelta(seconds=10)]

            if not recent.empty:
                fig1 = px.line(recent, x="Tijd", y=["Temperature 1 (remote) [°C]", "Temperature 2 (sensor) [°C]"],
                               color="Actuator", title="Temperaturen")
                fig1.update_layout(
                    xaxis=dict(tickformat="%H:%M:%S"),
                    height=300,
                    margin=dict(t=40, b=40, l=40, r=20),
                    font=dict(size=12)
                )
                chart1.plotly_chart(fig1)


                # Delta T grafiek met grenzen
                fig2 = make_subplots(specs=[[{"secondary_y": True}]])
                fig2.add_trace(go.Scatter(x=recent["Tijd"], y=recent["Delta T [°C]"],
                                         mode='lines', name="ΔT", line=dict(color='green')))
                fig2.add_trace(go.Scatter(x=recent["Tijd"], y=[alarm_settings[ip]["dt_min"]] * len(recent),
                                         mode='lines', name="ΔT Min", line=dict(color='red', dash='dash')))
                fig2.add_trace(go.Scatter(x=recent["Tijd"], y=[alarm_settings[ip]["dt_max"]] * len(recent),
                                         mode='lines', name="ΔT Max", line=dict(color='red', dash='dash')))
                fig2.update_layout(
                    title="ΔT (°C) met grenzen",
                    xaxis_title="Tijd",
                    yaxis_title="ΔT (°C)",
                    showlegend=True,
                    xaxis=dict(tickformat="%H:%M:%S"),
                    height=300,  # bijv. 400px hoogte
                    margin=dict(t=40, b=40, l=40, r=20),
                    font=dict(size=12)
                )
                chart2.plotly_chart(fig2, use_container_width=True)

                # Flow grafiek met grenzen
                fig3 = make_subplots(specs=[[{"secondary_y": True}]])
                fig3.add_trace(go.Scatter(x=recent["Tijd"], y=recent["Flow [m^3/h]"],
                                         mode='lines', name="Flow", line=dict(color='blue')))
                fig3.add_trace(go.Scatter(x=recent["Tijd"], y=[alarm_settings[ip]["flow_min"]] * len(recent),
                                         mode='lines', name="Flow Min", line=dict(color='red', dash='dash')))
                fig3.add_trace(go.Scatter(x=recent["Tijd"], y=[alarm_settings[ip]["flow_max"]] * len(recent),
                                         mode='lines', name="Flow Max", line=dict(color='red', dash='dash')))
                fig3.update_layout(
                    title="Flow m^3/h met grenzen",
                    xaxis_title="Tijd",
                    yaxis_title="Flow m^3/h",
                    showlegend=True,
                    xaxis=dict(tickformat="%H:%M:%S"),
                    height=300,
                    margin=dict(t=40, b=40, l=40, r=20),
                    font=dict(size=12)
                )
                chart3.plotly_chart(fig3, use_container_width=True)

            time.sleep(2)

    # --- TAB 3 ---
    with tab3:
        st.subheader("📊 Analyseer Data")
        selected_actuators_tab3 = st.multiselect("Kies één of meerdere actuatoren:", belimo_ips, default=[belimo_ips[0]])

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            start_hour = st.selectbox("Start uur", list(range(24)), index=0)
        with col2:
            start_min = st.selectbox("Start minuut", list(range(60)), index=0)
        with col3:
            start_sec = st.selectbox("Start seconde", list(range(60)), index=0)
        with col4:
            end_hour = st.selectbox("Eind uur", list(range(24)), index=23)
        with col5:
            end_min = st.selectbox("Eind minuut", list(range(60)), index=59)
        with col6:
            end_sec = st.selectbox("Eind seconde", list(range(60)), index=59)

        start_time = pd.to_datetime(f"1900-01-01 {start_hour:02}:{start_min:02}:{start_sec:02}")
        end_time = pd.to_datetime(f"1900-01-01 {end_hour:02}:{end_min:02}:{end_sec:02}")

        st.session_state["data_log"]["Tijd"] = pd.to_datetime(st.session_state["data_log"]["Tijd"])


        if st.button("Genereer grafiek"):
            filtered_data = st.session_state["data_log"].loc[
                (st.session_state["data_log"]["Tijd"] >= start_time) &
                (st.session_state["data_log"]["Tijd"] <= end_time) &
                (st.session_state["data_log"]["Actuator"].isin(selected_actuators_tab3))
            ]
            if not filtered_data.empty:
                fig1 = px.line(filtered_data, x="Tijd", y=["Temperature 1 (remote) [°C]", "Temperature 2 (sensor) [°C]"],
                               color="Actuator", title="Temperaturen")
                fig1.update_layout(xaxis=dict(tickformat="%H:%M:%S"))
                st.plotly_chart(fig1, use_container_width=True)

                fig2 = px.line(filtered_data, x="Tijd", y="Delta T [°C]",
                               color="Actuator", title="Delta T",
                               color_discrete_sequence=px.colors.qualitative.Set2)
                fig2.update_layout(xaxis=dict(tickformat="%H:%M:%S"))
                st.plotly_chart(fig2, use_container_width=True)
                
                fig3 = px.line(filtered_data, x="Tijd", y="Flow [m^3/h]",
                               color="Actuator", title="Flow [m^3/h]",
                               color_discrete_sequence=px.colors.qualitative.Set3)
                fig3.update_layout(xaxis=dict(tickformat="%H:%M:%S"))
                st.plotly_chart(fig3, use_container_width=True)
                
            else:
                st.warning("Geen data beschikbaar.")

        # Download knoppen
        all_data_csv = convert_df_to_csv(st.session_state["data_log"])
        st.download_button("Download Alle Data", all_data_csv, "alle_data.csv", "text/csv")

        if 'filtered_data' in locals() and not filtered_data.empty:
            st.download_button("Download Gefilterde Data",
                               convert_df_to_csv(filtered_data),
                               "gefilterde_data.csv",
                               "text/csv")


if __name__ == "__main__":
    main()



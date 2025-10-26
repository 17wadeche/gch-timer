import streamlit as st, requests, time

st.set_page_config(page_title="Smoke Test", layout="wide")
st.title("Streamlit Smoke Test")

API_BASE = "https://gch-timer-api.onrender.com"

st.write("Python version OK. Now checking API…")
t0 = time.time()
r = requests.get(f"{API_BASE}/", timeout=30)
st.write("Status:", r.status_code, "Body:", r.text, "ms:", int((time.time()-t0)*1000))
st.success("If you can see this, Streamlit is running.")

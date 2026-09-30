import os
import logging
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv
from api.launch_component import build_digio_component
from api.streamlit_client import KycGatewayError, create_session, get_session_status

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

logging_str = "[%(asctime)s: %(levelname)s: %(module)s]: %(message)s"
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(filename=os.path.join(log_dir,"ekyc_logs.log"), level=logging.INFO, format=logging_str, filemode="a")


# Set and Edit  wider (width) page of a layout
def wider_page():
    max_width_str = "max-width: 1200px;"
    st.markdown(
        f"""
        <style>
            .reportview-container .main .block-container{{ {max_width_str} }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    logging.info("Page layout set to wider configuration.")

# Used for Customized Streamlit theme (Frontend Only)
def set_custom_theme():
    st.markdown(
        """
        <style>
            body {
                background-color: #f0f2f6; /* Set background color */
                color: #333333; /* Set text color */
            }
            .sidebar .sidebar-content {
                background-color: #ffffff; /* Set sidebar background color */
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    logging.info("Custom theme applied to Streamlit app.")


# Sidebar Menu Content
def sidebar_section():
    st.sidebar.title("Select ID Card Type")
    option = st.sidebar.selectbox("ID card type", ("PAN", "AADHAR"))
    logging.info(f"ID card type selected: {option}")
    return option

# Header Content
def header_section(option):
    if option == "AADHAR":
        st.title("Registration Using Aadhar Card")
        logging.info("Header set for Aadhar Card registration.")
    elif option == "PAN":
        st.title("Registration Using PAN Card")
        logging.info("Header set for PAN Card registration.")


def main():
    wider_page()
    set_custom_theme()
    st.title("Identity Verification")
    st.caption("Verification is completed in Digio's hosted KYC flow.")
    document_type = st.selectbox("Document type", ("PAN", "AADHAAR"))
    customer_identifier = st.text_input("Email or mobile number")
    consent = st.checkbox(
        "I consent to Digio processing my identity document and selfie for this KYC request. "
        "The website will receive the verification status, not retain my uploaded images."
    )

    if st.button(
        "Start secure verification",
        type="primary",
        disabled=not customer_identifier.strip() or not consent,
    ):
        try:
            session = create_session(customer_identifier.strip(), document_type)
            st.session_state["digio_kyc_session"] = session
            st.success("Verification request created. Continue in Digio's secure flow below.")
        except KycGatewayError as exc:
            logging.warning("Could not start Digio KYC session: %s", exc)
            st.error(str(exc))

    session = st.session_state.get("digio_kyc_session")
    if session:
        st.components.v1.html(build_digio_component(session), height=150, scrolling=False)
        if st.button("Refresh verification status"):
            try:
                status = get_session_status(session["session_id"])
                if status["verified"]:
                    st.success("Digio has approved this verification.")
                elif status["final"]:
                    st.error(f"Digio verification status: {status['status']}.")
                else:
                    st.info("Digio is still processing. Refresh again in a moment.")
            except KycGatewayError as exc:
                st.error(str(exc))

        if st.button("Start a different verification"):
            del st.session_state["digio_kyc_session"]
            st.rerun()

if __name__ == "__main__":
    main()

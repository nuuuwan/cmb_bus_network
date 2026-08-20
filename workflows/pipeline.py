from cbn.core.Network import Network
from cbn.core.Place import Place


def run_network():
    network = Network()
    network.plot()
    network.Analyse()


def run_all():
    Place.fill_all_latlng()
    Place.remove_too_far()
    Place.remove_all_but_closest()
    Place.analyze_coverage()
    run_network()
    Place.open_uncovered_gnds_in_google_maps(limit=10)


if __name__ == "__main__":
    run_network()

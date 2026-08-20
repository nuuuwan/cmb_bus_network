from cbn.core.Network import Network
from cbn.core.Place import Place


def run_network():
    network = Network()
    network.plot()
    network.plot(include_routes=False)
    network.Analyse()


def run_all():
    Place.fill_all_latlng()
    Place.analyze_coverage()
    run_network()


if __name__ == "__main__":
    run_all()
